from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class CsvUserRow:
    line_index: int
    values: dict[str, str]


class CsvStore:
    def __init__(self, csv_path: Path) -> None:
        self.csv_path = csv_path
        self._thread_lock = threading.Lock()
        self._lock_path = csv_path.with_suffix(csv_path.suffix + ".lock")

    def list_users(self) -> list[dict[str, str | int]]:
        lines = self._read_lines()
        headers, rows = self._read_user_rows(lines)
        return [
            {
                "id": int(row.values.get("ID", "0") or 0),
                "user_id": row.values.get("UserId", ""),
                "name": row.values.get("Name", ""),
                "schedule_srelay": row.values.get("Schedule-SRelay", ""),
                "card_code": row.values.get("CardCode", ""),
            }
            for row in rows
            if row.values.get("ID", "").strip().isdigit()
        ]

    def get_user_by_id(self, user_id: int) -> dict[str, str] | None:
        lines = self._read_lines()
        _, rows = self._read_user_rows(lines)
        for row in rows:
            rid = row.values.get("ID", "").strip()
            if rid.isdigit() and int(rid) == user_id:
                return row.values
        return None

    def update_name(self, target_id: int, new_name: str) -> dict[str, str | int]:
        return self._update_field(target_id, "Name", new_name)

    def toggle_srelay(
        self,
        target_id: int,
        always_value: str = "1001-2;",
        never_value: str = "1002-2;",
    ) -> dict[str, str | int]:
        lines = self._read_lines()
        headers, rows = self._read_user_rows(lines)
        if "Schedule-SRelay" not in headers:
            raise ValueError("CSV missing Schedule-SRelay column")

        for row in rows:
            rid = row.values.get("ID", "").strip()
            if rid.isdigit() and int(rid) == target_id:
                current = row.values.get("Schedule-SRelay", "").strip()
                new_value = never_value if current == always_value else always_value
                updated = self._replace_cell(lines[row.line_index], headers.index("Schedule-SRelay"), new_value)
                lines[row.line_index] = updated
                self._write_lines_atomic(lines)
                return {
                    "id": target_id,
                    "field": "Schedule-SRelay",
                    "old_value": current,
                    "new_value": new_value,
                }

        raise KeyError(f"User ID {target_id} not found")

    def _update_field(self, target_id: int, field_name: str, new_value: str) -> dict[str, str | int]:
        lines = self._read_lines()
        headers, rows = self._read_user_rows(lines)
        if field_name not in headers:
            raise ValueError(f"CSV missing {field_name} column")

        for row in rows:
            rid = row.values.get("ID", "").strip()
            if rid.isdigit() and int(rid) == target_id:
                old = row.values.get(field_name, "")
                updated = self._replace_cell(lines[row.line_index], headers.index(field_name), new_value)
                lines[row.line_index] = updated
                self._write_lines_atomic(lines)
                return {
                    "id": target_id,
                    "field": field_name,
                    "old_value": old,
                    "new_value": new_value,
                }

        raise KeyError(f"User ID {target_id} not found")

    def _read_user_rows(self, lines: list[str]) -> tuple[list[str], list[CsvUserRow]]:
        header_index = -1
        for i, line in enumerate(lines):
            if "UserId" in line and line.lstrip().startswith("ID"):
                header_index = i
                break

        if header_index < 0:
            raise ValueError("Could not find UserData header row")

        headers = [self._clean_cell(cell) for cell in self._split_cells(lines[header_index])]

        rows: list[CsvUserRow] = []
        schedule_data_index = next((i for i, ln in enumerate(lines) if ln.strip().startswith("ScheduleData")), len(lines))

        for i in range(header_index + 1, schedule_data_index):
            cells = self._split_cells(lines[i])
            if not cells:
                continue
            row_id = self._clean_cell(cells[0])
            if not row_id.isdigit():
                continue
            values: dict[str, str] = {}
            for idx, name in enumerate(headers):
                values[name] = self._clean_cell(cells[idx]) if idx < len(cells) else ""
            rows.append(CsvUserRow(line_index=i, values=values))

        return headers, rows

    def _write_lines_atomic(self, lines: list[str]) -> None:
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        with self._thread_lock, self._file_lock():
            timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
            backup_dir = self.csv_path.parent / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = backup_dir / f"{self.csv_path.stem}.csv.bak.{timestamp}"
            shutil.copy2(self.csv_path, backup_path)

            fd, tmp_name = tempfile.mkstemp(prefix="csvtmp-", suffix=".csv", dir=str(self.csv_path.parent))
            os.close(fd)
            tmp_path = Path(tmp_name)
            try:
                tmp_path.write_text("".join(lines), encoding="utf-8", newline="")
                os.replace(tmp_path, self.csv_path)
            finally:
                if tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)

    @contextmanager
    def _file_lock(self):
        retries = 50
        for _ in range(retries):
            try:
                fd = os.open(self._lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                os.write(fd, str(os.getpid()).encode("ascii", errors="ignore"))
                os.close(fd)
                break
            except FileExistsError:
                time.sleep(0.1)
        else:
            raise TimeoutError("Could not acquire CSV lock")

        try:
            yield
        finally:
            self._lock_path.unlink(missing_ok=True)

    @staticmethod
    def _split_cells(line: str) -> list[str]:
        return line.rstrip("\n").split(",")

    @staticmethod
    def _clean_cell(cell: str) -> str:
        return cell.strip()

    @staticmethod
    def _replace_cell(line: str, index: int, new_value: str) -> str:
        newline = "\n" if line.endswith("\n") else ""
        cells = line.rstrip("\n").split(",")
        if index >= len(cells):
            raise IndexError("CSV field index out of range")

        original = cells[index]
        left_padding = len(original) - len(original.lstrip(" "))
        right_padding = len(original) - len(original.rstrip(" "))

        prefix = " " * left_padding
        suffix = " " * right_padding
        replacement = f"{prefix}{new_value}{suffix}"

        if len(replacement) < len(original):
            replacement = replacement + (" " * (len(original) - len(replacement)))

        cells[index] = replacement
        return ",".join(cells) + newline

    def _read_lines(self) -> list[str]:
        if not self.csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {self.csv_path}")
        return self.csv_path.read_text(encoding="utf-8").splitlines(keepends=True)
