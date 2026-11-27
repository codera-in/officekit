"""C20: work-hours "Download..." CSV carries the rows and the ISO-week totals, and they reconcile with the JSON totals."""

import csv
import io
import unittest
from datetime import datetime, timezone

from officekit.engines.engine_calculators_extra import ExtendedCalculatorEngine as Engine
from officekit.engines.engine_result_exports import ResultExportEngine

SHIFTS = [
    {"date": "2026-03-02", "start": "09:00", "end": "17:30", "break_minutes": 30},
    {"date": "2026-03-03", "start": "22:00", "end": "06:00", "break_minutes": 0},
    {"date": "2026-03-09", "start": "08:00", "end": "12:00", "break_minutes": 0},
]
EXPORTED_AT = datetime(2026, 10, 22, 9, 5, tzinfo=timezone.utc)

EXPECTED_LINES = [
    "record_type,section,name,value,unit,value_type,row_index,column_index",
    "metadata,report,tool_id,work_hours,,string,,",
    "metadata,report,title,Work hours,,string,,",
    "metadata,report,operation_time,2026-10-22T09:00:00+00:00,,string,,",
    "metadata,report,exported_at,2026-10-22T09:05:00+00:00,,string,,",
    "result,results,total_minutes,1200,,integer,,",
    "result,results,total_hours,20.0,,number,,",
    "assumption,assumptions,assumption,dst: not_applied,,string,,",
    "assumption,assumptions,assumption,overnight: end_before_start,,string,,",
    "table_cell,rows,index,1,,integer,1,1",
    "table_cell,rows,worked_minutes,480,,integer,1,2",
    "table_cell,rows,overnight,false,,boolean,1,3",
    "table_cell,rows,dst_adjusted_minutes,0,,integer,1,4",
    "table_cell,rows,index,2,,integer,2,1",
    "table_cell,rows,worked_minutes,480,,integer,2,2",
    "table_cell,rows,overnight,true,,boolean,2,3",
    "table_cell,rows,dst_adjusted_minutes,0,,integer,2,4",
    "table_cell,rows,index,3,,integer,3,1",
    "table_cell,rows,worked_minutes,240,,integer,3,2",
    "table_cell,rows,overnight,false,,boolean,3,3",
    "table_cell,rows,dst_adjusted_minutes,0,,integer,3,4",
    "table_cell,weeks,iso_week,2026-W10,,string,1,1",
    "table_cell,weeks,total_minutes,960,,integer,1,2",
    "table_cell,weeks,iso_week,2026-W11,,string,2,1",
    "table_cell,weeks,total_minutes,240,,integer,2,2",
]


def snapshot_from_work_hours(result):
    """The request body the result dialog builds from a work-hours result (same tables, results and assumptions)."""
    row_columns = ["index", "worked_minutes", "overnight", "dst_adjusted_minutes"]
    week_columns = ["iso_week", "total_minutes"]
    return {
        "tool_id": "work_hours",
        "title": "Work hours",
        "created_at": "2026-10-22T09:00:00+00:00",
        "inputs": [],
        "results": [
            {"name": "total_minutes", "value": result["total_minutes"], "unit": None},
            {"name": "total_hours", "value": result["total_hours"], "unit": None},
        ],
        "assumptions": [f"{key}: {value}" for key, value in result["assumptions"].items()],
        "tables": [
            {
                "title": "rows",
                "columns": row_columns,
                "rows": [[row[column] for column in row_columns] for row in result["rows"]],
            },
            {
                "title": "weeks",
                "columns": ["iso_week", "total_minutes"],
                "rows": [[week[column] for column in ["iso_week", "total_minutes"]] for week in result["weeks"]],
            },
        ],
    }


class WorkHoursCsvTests(unittest.TestCase):
    maxDiff = None

    def export(self):
        result = Engine.calculate_work_hours(SHIFTS)
        return result, ResultExportEngine.csv(snapshot_from_work_hours(result), EXPORTED_AT)

    def test_csv_text_has_every_row_and_week_total_exactly(self):
        _, rendered = self.export()
        self.assertEqual(rendered, "\r\n".join(EXPECTED_LINES) + "\r\n")

    def test_csv_row_and_week_totals_reconcile_with_json_totals(self):
        result, rendered = self.export()
        records = list(csv.DictReader(io.StringIO(rendered)))
        row_minutes = sum(
            int(record["value"]) for record in records
            if record["section"] == "rows" and record["name"] == "worked_minutes"
        )
        week_minutes = sum(
            int(record["value"]) for record in records
            if record["section"] == "weeks" and record["name"] == "total_minutes"
        )
        reported_total = next(
            int(record["value"]) for record in records
            if record["record_type"] == "result" and record["name"] == "total_minutes"
        )
        self.assertEqual(reported_total, result["total_minutes"])
        self.assertEqual(row_minutes, result["total_minutes"])
        self.assertEqual(week_minutes, result["total_minutes"])
        self.assertEqual(
            [(week["iso_week"], week["total_minutes"]) for week in result["weeks"]],
            [("2026-W10", 960), ("2026-W11", 240)],
        )


if __name__ == "__main__":
    unittest.main()
