"""Calculators slice catalogue entries (C06–C07, C15–C25).

Development-only: none of these IDs is listed in release-profile.json tool_ids.
"""

TOOLS = [
    {"id": "weighted_average", "name": "Average & Weighted Average", "category": "Calculators", "tab": "calculators", "desc": "Mean of a pasted list, with optional weights and a skip-or-reject rule for blank values", "icon": "fa-calculator"},
    {"id": "fractions_ratios", "name": "Fractions & Ratios", "category": "Calculators", "tab": "calculators", "desc": "Exact fraction simplification, addition, subtraction, multiplication and division with mixed-number and decimal forms", "icon": "fa-divide"},
    {"id": "roi", "name": "Return on Investment (ROI)", "category": "Calculators", "tab": "calculators", "desc": "Net gain and ROI percentage from the amount invested, amount returned and optional fees; not annualised", "icon": "fa-chart-pie"},
    {"id": "cagr", "name": "Growth Rate (CAGR)", "category": "Calculators", "tab": "calculators", "desc": "Compound annual growth rate and growth multiple from a start value, end value and fractional years", "icon": "fa-arrow-trend-up"},
    {"id": "date_difference", "name": "Date Difference Calculator", "category": "Calculators", "tab": "calculators", "desc": "Days between two calendar dates with a years, months and days breakdown; calendar dates only", "icon": "fa-calendar-days"},
    {"id": "age_calculator", "name": "Age Calculator", "category": "Calculators", "tab": "calculators", "desc": "Exact age on a chosen date in years, months and days, with the next birthday", "icon": "fa-cake-candles"},
    {"id": "business_days", "name": "Business Days Calculator", "category": "Calculators", "tab": "calculators", "desc": "Working days between two dates with weekend choices and your own holiday list", "icon": "fa-briefcase"},
    {"id": "work_hours", "name": "Work Hours Calculator", "category": "Calculators", "tab": "calculators", "desc": "Hours worked per shift with breaks, overnight shifts, weekly totals and optional time-zone rules", "icon": "fa-clock"},
    {"id": "time_zone_converter", "name": "Time Zone Converter", "category": "Calculators", "tab": "calculators", "desc": "Convert a local date and time between time zones using that date's daylight-saving rules", "icon": "fa-globe"},
    {"id": "quadratic_solver", "name": "Quadratic Equation Solver", "category": "Calculators", "tab": "calculators", "desc": "Real, repeated or complex roots of ax² + bx + c with a residual check", "icon": "fa-function"},
    {"id": "gcd_lcm", "name": "GCD & LCM Calculator", "category": "Calculators", "tab": "calculators", "desc": "Greatest common divisor and least common multiple of two to one hundred whole numbers", "icon": "fa-table-cells"},
    {"id": "descriptive_statistics", "name": "Descriptive Statistics", "category": "Calculators", "tab": "calculators", "desc": "Mean, median, modes, range, variance and standard deviation for a sample or whole population", "icon": "fa-chart-column"},
    {"id": "geometry", "name": "Geometry Calculator", "category": "Calculators", "tab": "calculators", "desc": "Area, perimeter, volume and surface area for common 2D and 3D shapes in one length unit", "icon": "fa-shapes"},
]

KEYWORDS = {
    "weighted_average": ["average", "mean", "weighted average", "weights", "pasted list"],
    "fractions_ratios": ["fraction", "ratio", "simplify fraction", "mixed number", "rational"],
    "roi": ["return on investment", "roi", "investment return", "net gain", "fees"],
    "cagr": ["cagr", "growth rate", "compound annual growth", "annual growth", "growth multiple"],
    "date_difference": ["days between", "date difference", "days until", "number of days", "date gap"],
    "age_calculator": ["age", "birthday", "how old", "next birthday", "date of birth"],
    "business_days": ["working days", "business days", "workdays", "holidays", "weekends"],
    "work_hours": ["work hours", "shift hours", "timesheet", "overnight shift", "break minutes", "hours worked"],
    "time_zone_converter": ["time zone", "timezone", "convert time", "daylight saving", "dst", "utc"],
    "quadratic_solver": ["quadratic", "quadratic equation", "roots", "discriminant", "ax2"],
    "gcd_lcm": ["gcd", "lcm", "greatest common divisor", "least common multiple", "hcf"],
    "descriptive_statistics": ["statistics", "mean median mode", "standard deviation", "variance", "descriptive statistics"],
    "geometry": ["area", "perimeter", "volume", "surface area", "circle area", "triangle area", "cylinder volume"],
}
