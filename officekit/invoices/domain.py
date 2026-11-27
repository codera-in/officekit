"""Deterministic invoice arithmetic and library-scoped business operations."""

import calendar
import copy
import csv
import hashlib
import io
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, localcontext

from .models import Business, Client, Currency, Discount, Draft, Item, Line, Schedule, TaxProfile, Template, new_id

MAX_CSV_BYTES = 10 * 1024 * 1024


class InvoiceError(ValueError):
    def __init__(self, code, message, status=422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def fail(code, message, status=422):
    raise InvoiceError(code, message, status)


def amount(value, precision):
    return Decimal(value).quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_UP)


def money(value, precision):
    return format(amount(value, precision), f".{precision}f")


def calculate_totals(lines, currency, taxes, discount):
    """Allocate discounts in minor units and round visible tax components once."""
    precision = currency.precision
    with localcontext() as context:
        context.prec = 60
        raw = [amount(Decimal(line.quantity) * Decimal(line.rate), precision) for line in lines]
        subtotal = sum(raw, Decimal(0))
        reduction = Decimal(0)
        if discount.kind == "percent":
            reduction = amount(subtotal * Decimal(discount.value) / 100, precision)
        elif discount.kind == "fixed":
            reduction = amount(discount.value, precision)
        if reduction > subtotal:
            fail("DISCOUNT_EXCEEDS_TOTAL", "The discount exceeds the invoice subtotal.")
        allocated = [amount(reduction * value / subtotal, precision) if subtotal else Decimal(0) for value in raw]
        # Largest line absorbs the bounded allocation residual; other lines cannot go negative.
        index = max(range(len(raw)), key=raw.__getitem__)
        allocated[index] += reduction - sum(allocated)
        result_lines = []
        tax_totals = [Decimal(0) for _ in taxes.rows]
        net_total = Decimal(0)
        for index, (line, gross, allocated_discount) in enumerate(zip(lines, raw, allocated)):
            discounted = gross - allocated_discount
            factors = []
            accumulated = Decimal(0)
            for tax in taxes.rows:
                factor = Decimal(tax.rate) / 100 * (1 + accumulated if tax.mode == "compound" else 1)
                factors.append(factor)
                accumulated += factor
            taxable = not line.tax_exempt and bool(taxes.rows)
            net = amount(discounted / (1 + accumulated), precision) if taxes.inclusive and taxable else discounted
            line_taxes = [amount(net * factor, precision) if taxable else Decimal(0) for factor in factors]
            if taxes.inclusive and taxable:
                line_taxes[-1] += discounted - net - sum(line_taxes)
            total = net + sum(line_taxes)
            if total > Decimal("1000000000000000"):
                fail("AMOUNT_TOO_LARGE", "The calculated invoice exceeds the supported amount.")
            net_total += net
            tax_totals = [a + b for a, b in zip(tax_totals, line_taxes)]
            result_lines.append({"net": money(net, precision), "discount": money(allocated_discount, precision), "taxes": [money(value, precision) for value in line_taxes], "total": money(total, precision)})
        total = net_total + sum(tax_totals)
        if total > Decimal("1000000000000000"):
            fail("AMOUNT_TOO_LARGE", "The calculated invoice exceeds the supported amount.")
        return {"subtotal": money(subtotal, precision), "discount": money(reduction, precision), "net": money(net_total, precision), "taxes": [{**tax.model_dump(), "amount": money(value, precision)} for tax, value in zip(taxes.rows, tax_totals)], "total": money(total, precision), "lines": result_lines}


def next_occurrence(anchor, frequency, index):
    if frequency == "weekly":
        return anchor + timedelta(days=index * 7)
    step = {"monthly": 1, "quarterly": 3, "yearly": 12}[frequency] * index
    year, month = divmod(anchor.year * 12 + anchor.month - 1 + step, 12)
    return date(year, month + 1, min(anchor.day, calendar.monthrange(year, month + 1)[1]))


def get_record(state, collection, identifier):
    try:
        return state[collection][identifier]
    except KeyError:
        fail("NOT_FOUND", "The requested invoice record is unavailable.", 404)


def configuration(business, collection, identifier, default_field):
    selected = identifier or business[default_field]
    for value in business[collection]:
        if value["id"] == selected:
            return copy.deepcopy(value)
    fail("CONFIGURATION_UNAVAILABLE", "Choose configuration belonging to this business profile.")


class InvoiceService:
    def __init__(self, libraries, today=date.today, now=None):
        self.libraries, self.today = libraries, today
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat())

    def _meta(self, state, previous=None):
        now = self.now()
        return {"id": previous["id"] if previous else new_id(), "created_at": previous["created_at"] if previous else now, "updated_at": now, "library_revision": state["revision"] + 1}

    def _document(self, state, draft, previous=None):
        business = copy.deepcopy(get_record(state, "businesses", draft.business_id))
        client = copy.deepcopy(get_record(state, "clients", draft.client_id))
        if client["business_id"] != draft.business_id:
            fail("PROFILE_MISMATCH", "The client belongs to another business profile.")
        for line in draft.lines:
            if line.item_id and get_record(state, "items", line.item_id)["business_id"] != draft.business_id:
                fail("PROFILE_MISMATCH", "The item belongs to another business profile.")
        currency = draft.currency_override.model_dump() if draft.currency_override else configuration(business, "currencies", draft.currency_id, "default_currency_id")
        taxes = draft.tax_override.model_dump() if draft.tax_override else configuration(business, "tax_profiles", draft.tax_profile_id or client["tax_profile_id"], "default_tax_profile_id")
        template = draft.template_override.model_dump() if draft.template_override else configuration(business, "templates", draft.template_id, "default_template_id")
        methods = [method for method in business["payment_methods"] if method["enabled"] and (draft.payment_method_ids is None or method["id"] in draft.payment_method_ids)]
        if draft.payment_method_ids and len(methods) != len(set(draft.payment_method_ids)):
            fail("PAYMENT_METHOD_UNAVAILABLE", "Choose enabled payment methods from this profile.")
        totals = calculate_totals(draft.lines, Currency.model_validate(currency), TaxProfile.model_validate(taxes), draft.discount)
        return {**self._meta(state, previous), "business_id": draft.business_id, "kind": draft.kind, "state": "draft", "status": "Draft", "number": "DRAFT", "draft": draft.model_dump(mode="json"), "business": Business.model_validate({key: value for key, value in business.items() if key in Business.model_fields}).model_dump(mode="json"), "client": Client.model_validate({key: value for key, value in client.items() if key in Client.model_fields}).model_dump(mode="json"), "currency": currency, "tax_profile": taxes, "template": template, "payment_methods": methods, "totals": totals, "paid": money(0, currency["precision"]), "balance": totals["total"], "source_quote_id": None, "allocation_kind": None, "recurrence_key": None, "reason": ""}

    def status(self, document):
        result = copy.deepcopy(document)
        state = result["state"]
        if state in {"draft", "void", "accepted", "declined"}:
            result["status"] = state.title()
        elif result["kind"] != "invoice":
            result["status"] = "Expired" if result["draft"]["valid_until"] and result["draft"]["valid_until"] < self.today().isoformat() else "Issued"
        elif Decimal(result["balance"]) == 0:
            result["status"] = "Paid"
        elif result["draft"]["due_date"] and result["draft"]["due_date"] < self.today().isoformat():
            result["status"] = "Overdue"
        else:
            result["status"] = "Partially paid" if Decimal(result["paid"]) else "Issued"
        return result

    def record(self, library_id, collection, identifier):
        value = get_record(self.libraries.get(library_id).read(), collection, identifier)
        return self.status(value) if collection == "documents" else value

    def page(self, library_id, collection, business_id=None, search="", status=None, kind=None, start=None, end=None, sort="date", order="desc", limit=50, cursor=None):
        state = self.libraries.get(library_id).read()
        records = list(state[collection].values())
        if collection == "documents":
            records = [self.status(record) for record in records]
        records = [record for record in records if (not business_id or record.get("business_id", record["id"]) == business_id) and (not search or search.casefold() in json.dumps(record, ensure_ascii=False).casefold()) and (not status or record.get("status") == status) and (not kind or record.get("kind") == kind) and (not start or record.get("draft", {}).get("issue_date", "") >= start) and (not end or record.get("draft", {}).get("issue_date", "") <= end)]
        records.sort(key=lambda record: (Decimal(record.get("totals", {}).get("total", "0")) if sort == "amount" else record.get("draft", {}).get("issue_date", record["created_at"]), record["id"]), reverse=order == "desc")
        offset = 0
        if cursor:
            try:
                offset = int(cursor)
                if offset < 0:
                    raise ValueError
            except ValueError:
                fail("INVALID_CURSOR", "The page cursor is invalid.")
        return {"items": records[offset:offset + limit], "next_cursor": str(offset + limit) if offset + limit < len(records) else None}

    def save(self, library_id, collection, body, identifier=None):
        event = {"action": f"{collection}_{'updated' if identifier else 'created'}"}

        def mutate(state):
            previous = get_record(state, collection, identifier) if identifier else None
            data = body.model_dump(mode="json", exclude={"expected_revision", "source_draft_id"})
            if collection == "documents":
                if previous and previous["state"] != "draft":
                    fail("ISSUED_DOCUMENT", "Issued documents cannot be edited. Duplicate as a draft instead.", 409)
                value = self._document(state, Draft.model_validate(data), previous)
                if previous:
                    for key in ("source_quote_id", "allocation_kind", "recurrence_key"):
                        value[key] = previous[key]
            else:
                if collection != "businesses":
                    business = get_record(state, "businesses", data["business_id"])
                    if previous and previous["business_id"] != data["business_id"]:
                        fail("PROFILE_MISMATCH", "A saved record cannot move to another profile.")
                    if collection == "clients" and data["tax_profile_id"]:
                        configuration(business, "tax_profiles", data["tax_profile_id"], "default_tax_profile_id")
                    if collection == "schedules":
                        self._document(state, Draft.model_validate(data["draft"]))
                value = {**data, **self._meta(state, previous)}
            state[collection][value["id"]] = value
            event["business_id"] = value["id"] if collection == "businesses" else value["business_id"]
            if collection == "documents":
                event["document_id"] = value["id"]
            return copy.deepcopy(value)
        return self.libraries.get(library_id).transaction(body.expected_revision, mutate, event=event)

    def transition(self, library_id, identifier, body):
        repository = self.libraries.get(library_id)
        event = {"action": "document_" + body.action, "document_id": identifier}

        def mutate(state):
            document = get_record(state, "documents", identifier)
            event["business_id"] = document["business_id"]
            current, action = document["state"], body.action
            allowed = (action == "issue" and current == "draft") or (action in {"accept", "decline"} and current == "issued" and document["kind"] != "invoice") or (action == "void" and current in {"issued", "accepted", "declined"})
            if not allowed:
                fail("INVALID_TRANSITION", "This document state does not permit that action.", 409)
            if action == "void" and Decimal(document["paid"]):
                fail("PAYMENT_EXISTS", "Correct recorded payments before voiding this invoice.", 409)
            if action == "issue":
                business = get_record(state, "businesses", document["business_id"])
                policy = business["numbering"]
                year = document["draft"]["issue_date"][:4]
                prefix = policy[document["kind"] + "_prefix"] + (year + "-" if policy["reset"] == "yearly" else "")
                existing = [value["number"] for value in state["documents"].values() if value["business_id"] == document["business_id"] and value["kind"] == document["kind"] and value["state"] != "draft"]
                counter = policy["next_counter"]
                number = body.number or prefix + str(counter).zfill(policy["padding"])
                while not body.number and number in existing:
                    counter += 1
                    number = prefix + str(counter).zfill(policy["padding"])
                if number in existing or counter > 999999999:
                    fail("NUMBER_CONFLICT", "The invoice number is already used or the counter is exhausted.", 409)
                document["number"] = number
                document["archive_status"] = "pending"
                document["archive_message"] = "The invoice is issued; its PDF archive is pending."
            document["state"] = {"issue": "issued", "accept": "accepted", "decline": "declined", "void": "void"}[action]
            document["reason"] = body.reason
            document.update(self._meta(state, document))
            state["documents"][identifier] = self.status(document)
            if action == "issue":
                from .pdf import render_pdf
                render_pdf(state["documents"][identifier], repository)
            return copy.deepcopy(state["documents"][identifier])
        result = repository.transaction(body.expected_revision, mutate, event=event)
        if body.action == "issue":
            try:
                return self.archive(library_id, identifier, result["library_revision"])
            except (InvoiceError, OSError, ValueError):
                # Financial issue is already committed. Preserve its identity and retry only archival.
                return result
        return result

    def archive(self, library_id, identifier, expected_revision):
        from .pdf import render_pdf
        repository = self.libraries.get(library_id)
        state = repository.read()
        if state["revision"] != expected_revision:
            fail("REVISION_CONFLICT", "The invoice library changed. Reload before continuing.", 409)
        document = get_record(state, "documents", identifier)
        if document["state"] == "draft":
            fail("DRAFT_ARCHIVE", "Issue the document before archiving its PDF.", 409)
        if document.get("archive_status") == "ready":
            return self.status(document)
        repository.archive_document(identifier, document["draft"]["issue_date"], render_pdf(document, repository))

        def mutate(current):
            document = get_record(current, "documents", identifier)
            document.update(archive_status="ready", archive_message="")
            document.update(self._meta(current, document))
            return self.status(document)
        return repository.transaction(expected_revision, mutate, event={"action": "document_archived", "document_id": identifier, "business_id": document["business_id"]})

    def _payment(self, state, document, body):
        payload = body.model_dump(mode="json", exclude={"expected_revision"})
        existing = [entry for entry in state["payments"].values() if entry["idempotency_key"] == body.idempotency_key]
        if existing:
            if any(existing[0][key] != payload[key] for key in payload) or existing[0]["document_id"] != document["id"]:
                fail("IDEMPOTENCY_CONFLICT", "That request key belongs to another payment.", 409)
            return existing[0]
        precision = document["currency"]["precision"]
        value = Decimal(body.amount)
        if value != amount(value, precision):
            fail("CURRENCY_PRECISION", "The payment has more decimal places than this currency supports.")
        if document["kind"] != "invoice" or document["state"] != "issued" or value > Decimal(document["balance"]):
            fail("PAYMENT_STATE", "The payment exceeds the balance or this document cannot receive payments.", 409)
        entry = {**payload, **self._meta(state), "document_id": document["id"], "reversal_of": None, "reason": ""}
        state["payments"][entry["id"]] = entry
        document["paid"] = money(Decimal(document["paid"]) + value, precision)
        document["balance"] = money(Decimal(document["totals"]["total"]) - Decimal(document["paid"]), precision)
        document.update(self._meta(state, document))
        return entry

    def payment(self, library_id, identifier, body, correction=False):
        event = {"action": "payment_corrected" if correction else "payment_recorded", "document_id": identifier}

        def mutate(state):
            document = get_record(state, "documents", identifier)
            event["business_id"] = document["business_id"]
            if correction:
                original = get_record(state, "payments", body.payment_id)
                if original["document_id"] != identifier or original["reversal_of"] or any(entry["reversal_of"] == original["id"] for entry in state["payments"].values()):
                    fail("PAYMENT_CORRECTED", "That payment is unrelated or has already been corrected.", 409)
                reversal = {**original, **self._meta(state), "amount": str(-Decimal(original["amount"])), "reversal_of": original["id"], "reason": body.reason, "idempotency_key": new_id()}
                state["payments"][reversal["id"]] = reversal
                precision = document["currency"]["precision"]
                document["paid"] = money(Decimal(document["paid"]) - Decimal(original["amount"]), precision)
                document["balance"] = money(Decimal(document["totals"]["total"]) - Decimal(document["paid"]), precision)
                if body.replacement:
                    self._payment(state, document, body.replacement)
            else:
                self._payment(state, document, body)
            document.update(self._meta(state, document))
            return {"document": self.status(document), "payments": [entry for entry in state["payments"].values() if entry["document_id"] == identifier]}
        return self.libraries.get(library_id).transaction(body.expected_revision, mutate, event=event)

    def payments(self, library_id, identifier):
        state = self.libraries.get(library_id).read()
        get_record(state, "documents", identifier)
        return {"items": [entry for entry in state["payments"].values() if entry["document_id"] == identifier], "next_cursor": None}

    def convert(self, library_id, body):
        event = {"action": "quote_converted", "document_id": body.source_quote_id}

        def mutate(state):
            payload = body.model_dump(mode="json", exclude={"expected_revision"})
            existing = state["conversions"].get(body.idempotency_key)
            if existing:
                if existing["payload"] != payload:
                    fail("IDEMPOTENCY_CONFLICT", "That request key belongs to another conversion.", 409)
                return {"documents": [self.status(get_record(state, "documents", key)) for key in existing["document_ids"]]}
            source = get_record(state, "documents", body.source_quote_id)
            event["business_id"] = source["business_id"]
            if source["kind"] == "invoice" or source["state"] != "accepted":
                fail("QUOTE_NOT_ACCEPTED", "Accept the quote before converting it.", 409)
            allocated = [entry for entry in state["documents"].values() if entry["source_quote_id"] == source["id"] and entry["state"] != "void"]
            remaining = Decimal(source["totals"]["total"]) - sum((Decimal(entry["totals"]["total"]) for entry in allocated), Decimal(0))
            value = Decimal(body.amount) if body.kind == "deposit" and body.amount is not None else remaining
            if value <= 0 or value > remaining or (body.kind == "full" and allocated):
                fail("ALLOCATION_CONFLICT", "The requested invoice exceeds the unallocated quote balance.", 409)
            precision = source["currency"]["precision"]
            if value != amount(value, precision):
                fail("CURRENCY_PRECISION", "The allocation exceeds the currency precision.")
            document = copy.deepcopy(source)
            document.update(self._meta(state))
            document.update({"kind": "invoice", "state": "draft", "status": "Draft", "number": "DRAFT", "source_quote_id": source["id"], "allocation_kind": body.kind, "paid": money(0, precision), "balance": money(value, precision)})
            document["draft"].update({"kind": "invoice", "valid_until": None, "issue_date": self.today().isoformat(), "due_date": (self.today() + timedelta(days=source["client"]["terms_days"])).isoformat(), "discount": {"kind": "none", "value": "0"}})
            fraction = value / Decimal(source["totals"]["total"])
            net = amount(Decimal(source["totals"]["net"]) * fraction, precision)
            taxes = [{**tax, "amount": money(Decimal(tax["amount"]) * fraction, precision)} for tax in source["totals"]["taxes"]]
            if taxes:
                taxes[-1]["amount"] = money(value - net - sum((Decimal(tax["amount"]) for tax in taxes[:-1]), Decimal(0)), precision)
            else:
                net = value
            document["draft"]["lines"] = [{"description": f"{body.kind.title()} invoice for {source['number']}", "item_id": None, "unit": "", "date": None, "quantity": "1", "rate": money(value if source["tax_profile"]["inclusive"] else net, precision), "tax_exempt": False, "section": ""}]
            document["totals"] = {"subtotal": document["draft"]["lines"][0]["rate"], "discount": money(0, precision), "net": money(net, precision), "taxes": taxes, "total": money(value, precision), "lines": [{"net": money(net, precision), "discount": money(0, precision), "taxes": [tax["amount"] for tax in taxes], "total": money(value, precision)}]}
            state["documents"][document["id"]] = document
            state["conversions"][body.idempotency_key] = {"payload": payload, "document_ids": [document["id"]]}
            return {"documents": [copy.deepcopy(document)]}
        return self.libraries.get(library_id).transaction(body.expected_revision, mutate, event=event)

    def recurring(self, library_id, body):
        def mutate(state):
            created, existing, remaining, approval = [], 0, 0, []
            keys = {document["recurrence_key"] for document in state["documents"].values()}
            for stored in state["schedules"].values():
                schedule = Schedule.model_validate({key: value for key, value in stored.items() if key not in {"id", "created_at", "updated_at", "library_revision"}})
                if schedule.paused:
                    continue
                for index in range(schedule.end_count or 10000):
                    occurrence = next_occurrence(schedule.anchor_date, schedule.frequency, index)
                    if occurrence > self.today() or (schedule.end_date and occurrence > schedule.end_date):
                        break
                    key = f"{stored['id']}:{occurrence.isoformat()}"
                    if key in keys:
                        existing += 1
                        continue
                    if schedule.catch_up == "ask" and stored["id"] not in body.approved_schedule_ids:
                        approval.append(stored["id"])
                        break
                    if len(created) == 100:
                        remaining += 1
                        continue
                    draft = schedule.draft.model_copy(deep=True)
                    terms = (draft.due_date - draft.issue_date).days if draft.due_date else 14
                    draft.issue_date, draft.due_date, draft.valid_until = occurrence, occurrence + timedelta(days=terms), None
                    document = self._document(state, draft)
                    document["recurrence_key"] = key
                    state["documents"][document["id"]] = document
                    keys.add(key)
                    created.append(document["id"])
            return {"created_document_ids": created, "existing_count": existing, "remaining_count": remaining, "approval_required": approval}
        return self.libraries.get(library_id).transaction(body.expected_revision, mutate, event={"action": "recurring_drafts_created"})

    def preview(self, library_id, body):
        state = self.libraries.get(library_id).read()
        if state["revision"] != body.expected_revision:
            fail("REVISION_CONFLICT", "The invoice library changed. Reload before continuing.", 409)
        return self.record(library_id, "documents", body.document_id) if body.document_id else self._document(state, body.draft)

    def report(self, library_id, business_id, currency_id, start, end, client_id=None):
        if start > end or (end - start).days > 3660:
            fail("INVALID_DATE_RANGE", "Choose an ordered report period of at most ten years.")
        state = self.libraries.get(library_id).read()
        business = get_record(state, "businesses", business_id)
        currency = configuration(business, "currencies", currency_id, "default_currency_id")
        precision = currency["precision"]
        totals = {key: Decimal(0) for key in ("invoiced", "received", "outstanding", "overdue")}
        clients = {}
        for stored in state["documents"].values():
            document = self.status(stored)
            if document["business_id"] != business_id or document["kind"] != "invoice" or document["state"] != "issued" or document["currency"] != currency or (client_id and document["draft"]["client_id"] != client_id):
                continue
            client = clients.setdefault(document["draft"]["client_id"], {"client_id": document["draft"]["client_id"], "name": document["client"]["name"], **{key: Decimal(0) for key in totals}})
            if start.isoformat() <= document["draft"]["issue_date"] <= end.isoformat():
                client["invoiced"] += Decimal(document["totals"]["total"])
            if document["draft"]["issue_date"] <= end.isoformat():
                client["outstanding"] += Decimal(document["balance"])
                if document["status"] == "Overdue":
                    client["overdue"] += Decimal(document["balance"])
            for payment in state["payments"].values():
                if payment["document_id"] == document["id"] and start.isoformat() <= payment["date"] <= end.isoformat():
                    client["received"] += Decimal(payment["amount"])
        for client in clients.values():
            for key in totals:
                totals[key] += client[key]
                client[key] = money(client[key], precision)
        return {"business_id": business_id, "currency": currency, "start": start.isoformat(), "end": end.isoformat(), **{key: money(value, precision) for key, value in totals.items()}, "clients": list(clients.values())}


def report_csv(report):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Client", "Currency", "Invoiced", "Received", "Outstanding", "Overdue"])
    for client in report["clients"]:
        label = client["name"]
        safe_label = "'" + label if label.lstrip().startswith(("=", "+", "-", "@")) else label
        writer.writerow([safe_label, report["currency"]["code"], client["invoiced"], client["received"], client["outstanding"], client["overdue"]])
    result = output.getvalue().encode("utf-8-sig")
    if len(result) > MAX_CSV_BYTES:
        fail("REPORT_TOO_LARGE", "The CSV report exceeds the supported size.", 413)
    return result
