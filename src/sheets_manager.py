"""Google Sheets manager for profile data operations."""

import gspread
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
        self.gc = gspread.service_account(filename=credentials_file)
        
        # Open spreadsheet
        spreadsheet_name = sheets_config.get("spreadsheet_name")
        spreadsheet_id = sheets_config.get("spreadsheet_id")
        
        if spreadsheet_id:
            self.spreadsheet = self.gc.open_by_key(spreadsheet_id)
        elif spreadsheet_name:
            self.spreadsheet = self.gc.open(spreadsheet_name)
        else:
            raise ValueError("Either spreadsheet_name or spreadsheet_id must be provided")
        
        # Get worksheet
        worksheet_name = sheets_config.get("worksheet_name", "Sheet1")
        self.worksheet = self.spreadsheet.worksheet(worksheet_name)
        
        # Column mapping
        self.columns = config.get("columns", {})
        self.col_profile = self.columns.get("profile_number", 1)
        self.col_address = self.columns.get("address", 2)
        self.col_date_work = self.columns.get("date_work", 3)
        self.col_yes_no = self.columns.get("yes_no_work", 4)
        self.col_kol_vo = self.columns.get("kol_vo_zapros", 5)
        self.col_status = self.columns.get("status", 6)
        
        # Cooldown hours
        self.cooldown_hours = config.get("automation", {}).get("cooldown_hours", 24)
        
        logger.info(f"Connected to spreadsheet: {self.spreadsheet.title}")
    
    def get_all_profiles(self) -> list[dict]:
        """
        Get all profiles from the spreadsheet.
        
        Returns:
            List of profile dicts with row numbers
        """
        # Get all values
        all_values = self.worksheet.get_all_values()
        
        profiles = []
        for row_idx, row in enumerate(all_values, start=1):
            # Skip header row if present (check if first column looks like a serial number)
            if row_idx == 1:
                # Try to detect if it's a header
                first_cell = row[self.col_profile - 1] if len(row) >= self.col_profile else ""
                if not first_cell.isdigit() and first_cell.lower() in ["profile", "profile number", "serial", "number", "#"]:
                    continue
            
            # Get values with safe indexing
            profile_number = row[self.col_profile - 1] if len(row) >= self.col_profile else ""
            address = row[self.col_address - 1] if len(row) >= self.col_address else ""
            date_work = row[self.col_date_work - 1] if len(row) >= self.col_date_work else ""
            yes_no = row[self.col_yes_no - 1] if len(row) >= self.col_yes_no else ""
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
                "yes_no_work": yes_no.strip().lower(),
                "kol_vo_zapros": int(kol_vo) if kol_vo.strip().isdigit() else 0,
                "status": status.strip()
            })
        
        logger.info(f"Found {len(profiles)} profiles in spreadsheet")
        return profiles
    
    def get_profiles_to_process(self) -> list[dict]:
        """
        Get profiles that need processing (cooldown passed).
        
        Returns:
            List of profiles ready for processing
        """
        all_profiles = self.get_all_profiles()
        
        ready_profiles = []
        for profile in all_profiles:
            # Check if cooldown has passed
            if is_cooldown_passed(profile["date_work"], self.cooldown_hours):
                ready_profiles.append(profile)
            else:
                logger.debug(
                    f"Profile {profile['profile_number']} skipped - cooldown not passed"
                )
        
        logger.info(f"{len(ready_profiles)} profiles ready for processing")
        return ready_profiles
    
    def update_profile_result(
        self,
        row: int,
        success: bool,
        status_message: str,
        current_count: int
    ):
        """
        Update profile result after processing.
        
        Args:
            row: Row number in spreadsheet (1-indexed)
            success: Whether the operation was successful
            status_message: Status message to write
            current_count: Current request count
        """
        now = datetime.now()
        date_str = format_date(now)
        new_count = current_count + 1 if success else current_count
        yes_no = "no"  # Just processed, need to wait cooldown
        
        # Batch update all cells
        updates = [
            (row, self.col_date_work, date_str),
            (row, self.col_yes_no, yes_no),
            (row, self.col_kol_vo, str(new_count)),
            (row, self.col_status, status_message)
        ]
        
        for r, c, value in updates:
            self.worksheet.update_cell(r, c, value)
        
        logger.info(
            f"Updated row {row}: date={date_str}, status={status_message}, count={new_count}"
        )
    
    def update_yes_no_column(self):
        """
        Update yes/no column for all profiles based on cooldown.
        Call this at the start to refresh status based on time.
        """
        all_profiles = self.get_all_profiles()
        
        for profile in all_profiles:
            expected_yes_no = get_yes_no_status(profile["date_work"], self.cooldown_hours)
            current_yes_no = profile["yes_no_work"]
            
            # Only update if different
            if expected_yes_no != current_yes_no:
                self.worksheet.update_cell(profile["row"], self.col_yes_no, expected_yes_no)
                logger.debug(
                    f"Updated yes/no for profile {profile['profile_number']}: {expected_yes_no}"
                )
        
        logger.info("Yes/No status updated for all profiles")
