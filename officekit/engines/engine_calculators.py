"""
OmniConvert - High Utility Business & Financial Calculators
Modeled after OmniCalculator / Calculator.net high-intent traffic drivers.
"""

from typing import Dict, Any, List
import math
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP, localcontext

class CalculatorEngine:

    @staticmethod
    def _percentage_number(name: str, value: float, maximum: float = 1e12) -> Decimal:
        """Validate a JSON-style numeric input and return its exact decimal spelling."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a finite number")
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite or value < 0 or value > maximum:
            raise ValueError(f"{name} must be between 0 and {maximum:,}")
        return Decimal(str(value))

    @staticmethod
    def _percentage_assumptions() -> Dict[str, str]:
        return {"rounding": "half_up", "precision": "0.01", "currency": "not_inferred", "taxes": "excluded"}

    @staticmethod
    def calculate_percent_of(percent: float, value: float) -> Dict[str, Any]:
        """Calculate a unit-neutral percentage of a value with half-up cent rounding."""
        rate = CalculatorEngine._percentage_number("percent", percent, 1_000_000)
        amount = CalculatorEngine._percentage_number("value", value)
        with localcontext() as context:
            context.prec = 40
            result = (rate * amount / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return {"percent": percent, "value": value, "result": float(result), "assumptions": CalculatorEngine._percentage_assumptions()}

    @staticmethod
    def calculate_percentage_change(original_value: float, new_value: float) -> Dict[str, Any]:
        """Calculate relative change from a positive baseline; zero baseline is undefined."""
        original = CalculatorEngine._percentage_number("original_value", original_value)
        current = CalculatorEngine._percentage_number("new_value", new_value)
        if original == 0:
            raise ValueError("original_value must be greater than zero for percentage change")
        with localcontext() as context:
            context.prec = 40
            difference = current - original
            change_value = difference.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            change_percent = (difference * Decimal("100") / original).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if abs(change_percent) > Decimal("1000000000000"):
            raise ValueError("Inputs produce a percentage change outside the supported range")
        direction = "increase" if difference > 0 else "decrease" if difference < 0 else "no_change"
        return {
            "original_value": original_value,
            "new_value": new_value,
            "change_value": float(change_value),
            "change_percent": float(change_percent),
            "direction": direction,
            "assumptions": CalculatorEngine._percentage_assumptions(),
        }

    @staticmethod
    def calculate_discount(price: float, discount_percent: float) -> Dict[str, Any]:
        """Calculate savings and discounted amount without assuming currency or tax."""
        amount = CalculatorEngine._percentage_number("price", price)
        rate = CalculatorEngine._percentage_number("discount_percent", discount_percent, 100)
        with localcontext() as context:
            context.prec = 40
            savings = (amount * rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            final = (amount - savings).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return {
            "price": price,
            "discount_percent": discount_percent,
            "savings": float(savings),
            "discounted_price": float(final),
            "assumptions": CalculatorEngine._percentage_assumptions(),
        }

    @staticmethod
    def calculate_loan_emi(principal: float, annual_interest_rate: float, tenure_years: float) -> Dict[str, Any]:
        """Calculate a fixed-rate monthly loan and its complete cent schedule."""
        values = {
            "principal": principal,
            "annual_interest_rate": annual_interest_rate,
            "tenure_years": tenure_years,
        }
        for name, value in values.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a finite number")
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError(f"{name} must be a finite number")
        if not 0 <= principal <= 1e12:
            raise ValueError("principal must be between 0 and 1,000,000,000,000")
        if not 0 <= annual_interest_rate <= 1000:
            raise ValueError("annual_interest_rate must be between 0% and 1,000%")
        if not (1 / 12) <= tenure_years <= 100:
            raise ValueError("tenure_years must be between one month and 100 years")

        exact_months = tenure_years * 12
        n = round(exact_months)
        if not math.isclose(exact_months, n, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("Loan tenure must resolve to a whole number of months")

        principal_value = Decimal(str(principal)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        monthly_rate = Decimal(str(annual_interest_rate)) / Decimal("1200")
        with localcontext() as context:
            context.prec = 40
            if monthly_rate == 0:
                regular_payment = (principal_value / n).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            else:
                growth = (Decimal("1") + monthly_rate) ** n
                regular_payment = (
                    principal_value * monthly_rate * growth / (growth - Decimal("1"))
                ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            balance = principal_value
            schedule: List[Dict[str, Any]] = []
            total_interest = Decimal("0.00")
            total_payment = Decimal("0.00")
            for month in range(1, n + 1):
                if balance == 0:
                    interest_paid = Decimal("0.00")
                    principal_paid = Decimal("0.00")
                    payment = Decimal("0.00")
                else:
                    interest_paid = (balance * monthly_rate).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                if balance != 0 and month == n:
                    principal_paid = balance
                    payment = principal_paid + interest_paid
                elif balance != 0:
                    principal_paid = regular_payment - interest_paid
                    if principal_paid <= 0:
                        raise ValueError("Payment does not reduce the loan balance")
                    if principal_paid >= balance:
                        principal_paid = balance
                    payment = principal_paid + interest_paid
                balance -= principal_paid
                total_interest += interest_paid
                total_payment += payment
                schedule.append({
                    "month": month,
                    "payment": float(payment),
                    "principal_paid": float(principal_paid),
                    "interest_paid": float(interest_paid),
                    "remaining_balance": float(balance),
                })

        return {
            "monthly_emi": float(regular_payment),
            "total_interest": float(total_interest),
            "total_payment": float(total_payment),
            "tenure_months": n,
            "preview_schedule": schedule[:12],
            "schedule": schedule,
            "assumptions": {
                "rate_basis": "nominal_annual",
                "payment_frequency": "monthly",
                "currency_precision": "0.01",
                "fees_and_extra_payments": "excluded",
                "final_payment": "adjusted_to_zero_balance",
            },
        }

    @staticmethod
    def calculate_compound_interest(principal: float, annual_rate: float, years: float, compound_freq: int = 12, monthly_contribution: float = 0.0) -> Dict[str, Any]:
        """Compute growth with equivalent monthly accrual and end-month deposits.

        ``compound_freq`` sets nominal compounding periods per year. Monthly
        accrual uses the mathematically equivalent effective monthly factor;
        this lets monthly contributions be timed consistently for annual,
        quarterly, monthly and daily compounding frequencies. A partial final
        month accrues interest proportionally and does not create a deposit.
        """
        values = {
            "principal": principal,
            "annual_rate": annual_rate,
            "years": years,
            "monthly_contribution": monthly_contribution,
        }
        for name, value in values.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a finite number")
            try:
                is_finite = math.isfinite(value)
            except OverflowError:
                is_finite = False
            if not is_finite:
                raise ValueError(f"{name} must be a finite number")
        if not 0 <= principal <= 1e12:
            raise ValueError("principal must be between 0 and 1,000,000,000,000")
        if not -100 < annual_rate <= 1000:
            raise ValueError("annual_rate must be greater than -100% and no more than 1,000%")
        if not 0 <= years <= 100:
            raise ValueError("years must be between 0 and 100")
        if type(compound_freq) is not int or not 1 <= compound_freq <= 365:
            raise ValueError("compound_freq must be an integer from 1 to 365")
        if not 0 <= monthly_contribution <= 1e12:
            raise ValueError("monthly_contribution must be between 0 and 1,000,000,000,000")

        monthly_factor = math.exp(
            math.log1p((annual_rate / 100.0) / compound_freq) * compound_freq / 12.0
        )
        exact_months = years * 12.0
        rounded_months = round(exact_months)
        if math.isclose(exact_months, rounded_months, rel_tol=0.0, abs_tol=1e-10):
            exact_months = float(rounded_months)
        full_months = math.floor(exact_months)
        partial_month = exact_months - full_months

        balance = float(principal)
        total_contributions = float(principal)
        growth_history: List[Dict[str, Any]] = []
        for month in range(1, full_months + 1):
            balance = balance * monthly_factor + monthly_contribution
            total_contributions += monthly_contribution
            if not math.isfinite(balance) or not math.isfinite(total_contributions):
                raise ValueError("Inputs exceed the supported calculation range")
            if month % 12 == 0:
                growth_history.append({
                    "year": month // 12,
                    "total_balance": round(balance, 2),
                    "total_invested": round(total_contributions, 2),
                    "total_interest": round(balance - total_contributions, 2),
                })

        if partial_month:
            balance *= monthly_factor ** partial_month
            if not math.isfinite(balance):
                raise ValueError("Inputs exceed the supported calculation range")

        if years > 0 and (not growth_history or growth_history[-1]["year"] != years):
            growth_history.append({
                "year": years,
                "total_balance": round(balance, 2),
                "total_invested": round(total_contributions, 2),
                "total_interest": round(balance - total_contributions, 2),
            })

        return {
            "future_value": round(balance, 2),
            "total_invested": round(total_contributions, 2),
            "total_interest_earned": round(balance - total_contributions, 2),
            "growth_history": growth_history,
            "assumptions": {
                "rate_basis": "nominal_annual",
                "monthly_accrual": "equivalent_effective_monthly_rate",
                "contribution_timing": "end_of_month",
                "fractional_month": "interest_only",
            },
        }

    @staticmethod
    def calculate_vat_salestax(amount: float, tax_rate_percent: float, is_inclusive: bool = False) -> Dict[str, Any]:
        """Calculates forward or reverse VAT/Sales Tax."""
        for name, value in (("amount", amount), ("tax_rate_percent", tax_rate_percent)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a finite number")
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError(f"{name} must be a finite number")
        if not 0 <= amount <= 1e12:
            raise ValueError("amount must be between 0 and 1,000,000,000,000")
        if not 0 <= tax_rate_percent <= 1000:
            raise ValueError("tax_rate_percent must be between 0% and 1,000%")
        if type(is_inclusive) is not bool:
            raise ValueError("is_inclusive must be a boolean")

        amount_decimal = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        tax_rate = Decimal(str(tax_rate_percent)) / Decimal("100")
        with localcontext() as context:
            context.prec = 40
            if is_inclusive:
                gross_amount = amount_decimal
                net_amount = (gross_amount / (Decimal("1") + tax_rate)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                tax_amount = gross_amount - net_amount
            else:
                net_amount = amount_decimal
                tax_amount = (net_amount * tax_rate).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                gross_amount = net_amount + tax_amount
        return {
            "net_amount": float(net_amount),
            "tax_amount": float(tax_amount),
            "gross_amount": float(gross_amount),
            "tax_rate_percent": tax_rate_percent,
            "is_inclusive": is_inclusive,
            "assumptions": {
                "rate_source": "user_supplied",
                "jurisdiction": "not_specified",
                "currency_precision": "0.01",
                "rounding": "half_up",
            },
        }

    @staticmethod
    def calculate_freelance_invoice_rate(target_annual_take_home: float, billable_hours_per_week: float = 30.0, vacation_weeks: float = 4.0, business_expenses_annual: float = 5000.0, tax_rate_percent: float = 25.0) -> Dict[str, Any]:
        """Calculates required hourly billing rate and day rate for freelancers & agencies."""
        values = {
            "target_annual_take_home": target_annual_take_home,
            "billable_hours_per_week": billable_hours_per_week,
            "vacation_weeks": vacation_weeks,
            "business_expenses_annual": business_expenses_annual,
            "tax_rate_percent": tax_rate_percent,
        }
        for name, value in values.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a finite number")
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError(f"{name} must be a finite number")
        if not 0 <= target_annual_take_home <= 1e12:
            raise ValueError("target_annual_take_home must be between 0 and 1,000,000,000,000")
        if not 0 < billable_hours_per_week <= 168:
            raise ValueError("billable_hours_per_week must be greater than 0 and no more than 168")
        if not 0 <= vacation_weeks < 52:
            raise ValueError("vacation_weeks must be at least 0 and less than 52")
        if not 0 <= business_expenses_annual <= 1e12:
            raise ValueError("business_expenses_annual must be between 0 and 1,000,000,000,000")
        if not 0 <= tax_rate_percent < 100:
            raise ValueError("tax_rate_percent must be between 0% and less than 100%")

        working_weeks = 52.0 - vacation_weeks
        total_billable_hours = working_weeks * billable_hours_per_week
        gross_required = (target_annual_take_home / (1.0 - tax_rate_percent / 100.0)) + business_expenses_annual
        hourly_rate = gross_required / total_billable_hours
        day_rate = hourly_rate * (billable_hours_per_week / 5.0)
        if not all(math.isfinite(value) for value in (gross_required, hourly_rate, day_rate)):
            raise ValueError("Inputs exceed the supported calculation range")

        return {
            "recommended_hourly_rate": round(hourly_rate, 2),
            "recommended_day_rate": round(day_rate, 2),
            "gross_annual_revenue_needed": round(gross_required, 2),
            "total_annual_billable_hours": round(total_billable_hours, 1),
            "assumptions": {
                "tax_treatment": "gross_up_target_then_add_expenses",
                "working_days_per_week": 5,
                "jurisdiction": "not_specified",
            },
        }

    @staticmethod
    def calculate_margin_markup(cost: float, revenue: float) -> Dict[str, Any]:
        """Calculates profit, gross margin %, and markup %."""
        for name, value in (("cost", cost), ("revenue", revenue)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a finite number")
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError(f"{name} must be a finite number")
            if not 0 <= value <= 1e12:
                raise ValueError(f"{name} must be between 0 and 1,000,000,000,000")
        cost_amount = Decimal(str(cost))
        revenue_amount = Decimal(str(revenue))
        profit = revenue_amount - cost_amount
        try:
            with localcontext() as context:
                context.prec = 40
                rounded_profit = profit.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                margin_pct = (
                    (profit / revenue_amount * Decimal("100")).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    if revenue_amount > 0 else None
                )
                markup_pct = (
                    (profit / cost_amount * Decimal("100")).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    if cost_amount > 0 else None
                )
        except ArithmeticError as error:
            raise ValueError("Inputs exceed the supported calculation range") from error
        if (
            not math.isfinite(float(rounded_profit))
            or (margin_pct is not None and not math.isfinite(float(margin_pct)))
            or (markup_pct is not None and not math.isfinite(float(markup_pct)))
        ):
            raise ValueError("Inputs exceed the supported calculation range")
        return {
            "profit": float(rounded_profit),
            "gross_margin_percent": float(margin_pct) if margin_pct is not None else None,
            "markup_percent": float(markup_pct) if markup_pct is not None else None,
            "cost": cost,
            "revenue": revenue,
            "assumptions": {"margin_denominator": "revenue", "markup_denominator": "cost"},
        }

    @staticmethod
    def calculate_break_even(fixed_costs: float, price_per_unit: float, cost_per_unit: float) -> Dict[str, Any]:
        """Calculates units and revenue required to reach zero profit/loss."""
        values = {
            "fixed_costs": fixed_costs,
            "price_per_unit": price_per_unit,
            "cost_per_unit": cost_per_unit,
        }
        for name, value in values.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a finite number")
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite or not 0 <= value <= 1e12:
                raise ValueError(f"{name} must be between 0 and 1,000,000,000,000")

        fixed = Decimal(str(fixed_costs))
        price = Decimal(str(price_per_unit))
        unit_cost = Decimal(str(cost_per_unit))
        contribution_margin = price - unit_cost
        if contribution_margin <= 0:
            raise ValueError("Price per unit must be greater than variable cost per unit.")
        with localcontext() as context:
            context.prec = 40
            units = int((fixed / contribution_margin).to_integral_value(rounding=ROUND_CEILING))
            revenue = units * price
        revenue_float = float(revenue)
        if not math.isfinite(revenue_float):
            raise ValueError("Inputs exceed the supported calculation range")
        return {
            "break_even_units": units,
            "break_even_revenue": round(revenue_float, 2),
            "contribution_margin": float(contribution_margin)
        }

    @staticmethod
    def calculate_depreciation(asset_cost: float, salvage_value: float, useful_life_years: int) -> Dict[str, Any]:
        """Calculate a bounded straight-line schedule with a cent-balanced final year."""
        for name, value in (("asset_cost", asset_cost), ("salvage_value", salvage_value)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a finite number")
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError(f"{name} must be a finite number")
            if not 0 <= value <= 1e12:
                raise ValueError(f"{name} must be between 0 and 1,000,000,000,000")
        if type(useful_life_years) is not int or not 1 <= useful_life_years <= 100:
            raise ValueError("useful_life_years must be a whole number from 1 to 100")

        cent = Decimal("0.01")
        cost = Decimal(str(asset_cost)).quantize(cent, rounding=ROUND_HALF_UP)
        salvage = Decimal(str(salvage_value)).quantize(cent, rounding=ROUND_HALF_UP)
        if salvage > cost:
            raise ValueError("salvage_value must not exceed asset_cost")
        depreciable_base = cost - salvage

        with localcontext() as context:
            context.prec = 40
            annual_exact = depreciable_base / Decimal(useful_life_years)
            annual_rounded = annual_exact.quantize(cent, rounding=ROUND_HALF_UP)
            remaining = depreciable_base
            book_value = cost
            schedule = []
            for year in range(1, useful_life_years + 1):
                depreciation = remaining if year == useful_life_years else min(annual_rounded, remaining)
                remaining -= depreciation
                book_value -= depreciation
                schedule.append({
                    "year": year,
                    "depreciation": float(depreciation),
                    "book_value": float(book_value),
                })
        return {
            "annual_depreciation": float(annual_rounded),
            "total_depreciable": float(depreciable_base),
            "schedule": schedule,
            "assumptions": {
                "method": "straight_line",
                "currency_precision": "0.01",
                "rounding": "half_up",
                "final_period": "adjusted_to_salvage_value",
            },
        }

    @staticmethod
    def calculate_simple_interest(
        principal: float,
        annual_rate_percent: float,
        time_value: float,
        time_unit: str,
    ) -> Dict[str, Any]:
        """Calculate simple interest for an explicitly selected years/months duration."""
        for name, value in (
            ("principal", principal),
            ("annual_rate_percent", annual_rate_percent),
            ("time_value", time_value),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a finite number")
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError(f"{name} must be a finite number")
        if not 0 <= principal <= 1e12:
            raise ValueError("principal must be between 0 and 1,000,000,000,000")
        if not 0 <= annual_rate_percent <= 1000:
            raise ValueError("annual_rate_percent must be between 0% and 1,000%")
        if not isinstance(time_unit, str) or time_unit not in {"years", "months"}:
            raise ValueError("time_unit must be either 'years' or 'months'")
        maximum_duration = 100 if time_unit == "years" else 1200
        if not 0 < time_value <= maximum_duration:
            raise ValueError(f"time_value must be greater than 0 and no more than {maximum_duration} {time_unit}")

        duration = Decimal(str(time_value))
        time_in_years = duration if time_unit == "years" else duration / Decimal("12")
        principal_amount = Decimal(str(principal)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        rate = Decimal(str(annual_rate_percent)) / Decimal("100")
        with localcontext() as context:
            context.prec = 40
            interest = (principal_amount * rate * time_in_years).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            total = principal_amount + interest

        return {
            "principal": float(principal_amount),
            "annual_rate_percent": annual_rate_percent,
            "time_value": time_value,
            "time_unit": time_unit,
            "time_in_years": float(time_in_years),
            "interest_amount": float(interest),
            "total_amount": float(total),
            "assumptions": {
                "method": "simple_interest",
                "rate_basis": "nominal_annual",
                "currency_precision": "0.01",
                "rounding": "half_up",
                "compounding": "none",
            },
        }
