"""Google Sheets manager for profile data operations."""

import gspread
from gspread.exceptions import SpreadsheetNotFound
from datetime import datetime
from typing import Optional
from src.utils import setup_logging, is_cooldown_passed, format_date, get_yes_no_status


logger = setup_logging("SheetsManager")


class SheetsManager:
    """Manager for Google Sheets operations."""
    
    def __init__(self, config: dict):
        """
        Initialize Sheets Manager.
        
        Args:
            config: Configuration dict with google_sheets and columns settings
        """
        self.config = config
        sheets_config = config.get("google_sheets", {})
        
        # Authenticate with service account
        credentials_file = sheets_config.get("credentials_file", "credentials.json")
        
        try:
            self.gc = gspread.service_account(filename=credentials_file)
        except FileNotFoundError:
            raise FileNotFoundError(
                f"Credentials file '{credentials_file}' not found!\n"
                "Please download the service account JSON key from Google Cloud Console "
                "and save it as 'credentials.json' in the project folder."
            )
        
        # Open spreadsheet
        spreadsheet_name = sheets_config.get("spreadsheet_name")
        spreadsheet_id = sheets_config.get("spreadsheet_id")
        
        # Auto-detect if spreadsheet_name looks like an ID (long alphanumeric string)
        if spreadsheet_name and len(spreadsheet_name) > 30 and spreadsheet_name.replace('-', '').replace('_', '').isalnum():
            # Looks like an ID, use it as such
            spreadsheet_id = spreadsheet_name
            spreadsheet_name = None
            logger.info(f"Detected spreadsheet_name as ID, using open_by_key")
        
        try:
            if spreadsheet_id:
                logger.info(f"Opening spreadsheet by ID: {spreadsheet_id[:20]}...")
                self.spreadsheet = self.gc.open_by_key(spreadsheet_id)
            elif spreadsheet_name:
                logger.info(f"Opening spreadsheet by name: {spreadsheet_name}")
                self.spreadsheet = self.gc.open(spreadsheet_name)
            else:
                raise ValueError("Either spreadsheet_name or spreadsheet_id must be provided in config")
        except SpreadsheetNotFound:
            # Get service account email for helpful error message
            try:
                sa_email = self.gc.auth.service_account_email
            except:
                sa_email = "(check credentials.json for 'client_email')"
            
            raise SpreadsheetNotFound(
                f"Spreadsheet not found!\n\n"
                f"Possible reasons:\n"
                f"1. Spreadsheet '{spreadsheet_name or spreadsheet_id}' does not exist\n"
                f"2. Spreadsheet is not shared with the service account\n\n"
                f"Solution: Share the spreadsheet with this email:\n"
                f"   {sa_email}\n\n"
                f"Or use 'spreadsheet_id' instead of 'spreadsheet_name' in config.yaml:\n"
                f"   spreadsheet_id: \"1ABC123...\" (from the URL)"
            )
        
        # Get worksheet
        worksheet_name = sheets_config.get("worksheet_name", "Sheet1")
        try:
            self.worksheet = self.spreadsheet.worksheet(worksheet_name)
        except gspread.exceptions.WorksheetNotFound:
            raise ValueError(
                f"Worksheet '{worksheet_name}' not found in spreadsheet '{self.spreadsheet.title}'.\n"
                f"Available worksheets: {[ws.title for ws in self.spreadsheet.worksheets()]}"
            )

        
        # Column mapping (removed yes_no_work - managed by formulas)
        self.columns = config.get("columns", {})
        self.col_profile = self.columns.get("profile_number", 1)
        self.col_address = self.columns.get("address", 2)
        self.col_date_work = self.columns.get("date_work", 3)
        self.col_kol_vo = self.columns.get("kol_vo_zapros", 5)
        self.col_status = self.columns.get("status", 6)
        
        # Cooldown hours
        self.cooldown_hours = config.get("automation", {}).get("cooldown_hours", 24)
        
        logger.info(f"Connected to spreadsheet: {self.spreadsheet.title}")
    
    def get_all_profiles(self) -> list[dict]:
        """
        Get all profiles from the spreadsheet (top to bottom).
        
        Returns:
            List of profile dicts with row numbers
        """
        # Get all values
        all_values = self.worksheet.get_all_values()
        
        profiles = []
        for row_idx, row in enumerate(all_values, start=1):
            # Skip header row if present
            if row_idx == 1:
                first_cell = row[self.col_profile - 1] if len(row) >= self.col_profile else ""
                if not first_cell.isdigit() and first_cell.lower() in ["profile", "profile number", "serial", "number", "#"]:
                    continue
            
            # Get values with safe indexing
            profile_number = row[self.col_profile - 1] if len(row) >= self.col_profile else ""
            address = row[self.col_address - 1] if len(row) >= self.col_address else ""
            date_work = row[self.col_date_work - 1] if len(row) >= self.col_date_work else ""
            kol_vo = row[self.col_kol_vo - 1] if len(row) >= self.col_kol_vo else ""
            status = row[self.col_status - 1] if len(row) >= self.col_status else ""
            
            # Skip empty rows
            if not profile_number:
                continue
            
            profiles.append({
                "row": row_idx,
                "profile_number": profile_number.strip(),
                "address": address.strip(),
                "date_work": date_work.strip(),
                "kol_vo_zapros": int(kol_vo) if kol_vo.strip().isdigit() else 0,
                "status": status.strip()
            })
        
        logger.info(f"Found {len(profiles)} profiles in spreadsheet")
        return profiles
    
    def get_profiles_to_process(self) -> list[dict]:
        """
        Get profiles that need processing (24h cooldown passed).
        Profiles are returned in order from top to bottom.
        
        Returns:
            List of profiles ready for processing
        """
        all_profiles = self.get_all_profiles()
        
        ready_profiles = []
        skipped_count = 0
        
        for profile in all_profiles:
            # Check if 24h cooldown has passed based on date_work
            if is_cooldown_passed(profile["date_work"], self.cooldown_hours):
                ready_profiles.append(profile)
            else:
                skipped_count += 1
                logger.debug(
                    f"Profile {profile['profile_number']} skipped - cooldown not passed"
                )
        
        logger.info(f"{len(ready_profiles)} profiles ready, {skipped_count} on cooldown")
        return ready_profiles
    
    def update_profile_result(
        self,
        row: int,
        success: bool,
        status_message: str,
        current_count: int
    ):
        """
        Update profile result after processing using batch update.
        Does NOT update yes/no_work - managed by spreadsheet formulas.
        
        Args:
            row: Row number in spreadsheet (1-indexed)
            success: Whether the operation was successful
            status_message: Status message to write
            current_count: Current request count
        """
        now = datetime.now()
        date_str = format_date(now)
        new_count = current_count + 1 if success else current_count
        
        # Use batch_update to update all cells in one API call
        def col_to_letter(col: int) -> str:
            """Convert column number to letter (1 -> A, 2 -> B, etc)"""
            result = ""
            while col > 0:
                col, remainder = divmod(col - 1, 26)
                result = chr(65 + remainder) + result
            return result
        
        # Prepare batch update data (NO yes_no - managed by formulas)
        updates = [
            {
                'range': f'{col_to_letter(self.col_date_work)}{row}',
                'values': [[date_str]]
            },
            {
                'range': f'{col_to_letter(self.col_kol_vo)}{row}',
                'values': [[str(new_count)]]
            },
            {
                'range': f'{col_to_letter(self.col_status)}{row}',
                'values': [[status_message]]
            }
        ]
        
        # Execute batch update
        self.worksheet.batch_update(updates)
        
        logger.info(
            f"Updated row {row}: date={date_str}, status={status_message}, count={new_count}"
        )
    
    def update_profile_with_cooldown(
        self,
        row: int,
        calculated_date: Optional[str]
    ):
        """
        Update profile when cooldown is detected from page timer.
        Does NOT update kol-vo_zapros or yes/no_work.
        
        Args:
            row: Row number in spreadsheet (1-indexed)
            calculated_date: Calculated last work date from timer, or None
        """
        # Use calculated date if available, otherwise leave empty
        date_str = calculated_date if calculated_date else ""
        status = "Cooldown"
        
        # Column letter helper
        def col_to_letter(col: int) -> str:
            result = ""
            while col > 0:
                col, remainder = divmod(col - 1, 26)
                result = chr(65 + remainder) + result
            return result
        
        # Prepare batch update (only date_work and status)
        updates = [
            {
                'range': f'{col_to_letter(self.col_date_work)}{row}',
                'values': [[date_str]]
            },
            {
                'range': f'{col_to_letter(self.col_status)}{row}',
                'values': [[status]]
            }
        ]
        
        self.worksheet.batch_update(updates)
        
        logger.info(
            f"Updated row {row} with cooldown: date={date_str}"
        )
