"""Invoice tax/total calculations - the ONE place this math happens.

Both the create-invoice view (authoritative, on save) and the live-preview
JS in templates/employees/invoices/create.html implement this same
arithmetic, but only this module's output is ever persisted - the client
side exists purely for instant UI feedback and is never trusted.
"""
from decimal import Decimal, ROUND_HALF_UP

TWO_PLACES = Decimal('0.01')

NO_TAX_INVOICE_TYPES = ('bill_of_supply', 'non_gst')


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def calculate_line(*, quantity, rate, discount_type, discount_value, tax_rate, invoice_type) -> dict:
    """Computes one line item. Raises ValueError on invalid input (negative
    quantity/rate, a fixed discount larger than the line, etc.) - the caller
    turns that into a form error instead of silently clamping."""
    quantity = Decimal(str(quantity))
    rate = Decimal(str(rate))
    discount_value = Decimal(str(discount_value or 0))
    tax_rate = Decimal(str(tax_rate or 0))

    if quantity <= 0:
        raise ValueError('Quantity must be greater than 0.')
    if rate < 0:
        raise ValueError('Rate cannot be negative.')
    if discount_value < 0:
        raise ValueError('Discount cannot be negative.')
    if tax_rate < 0:
        raise ValueError('Tax rate cannot be negative.')

    gross = quantity * rate

    if discount_type == 'percentage':
        if discount_value > 100:
            raise ValueError('Discount percentage cannot exceed 100%.')
        discount = gross * discount_value / Decimal('100')
    else:
        if discount_value > gross:
            raise ValueError('Discount cannot exceed the line amount.')
        discount = discount_value

    taxable = gross - discount

    if invoice_type in NO_TAX_INVOICE_TYPES:
        tax = Decimal('0')
    else:
        tax = taxable * tax_rate / Decimal('100')

    total = taxable + tax

    return {
        'gross': _money(gross),
        'discount': _money(discount),
        'taxable': _money(taxable),
        'tax': _money(tax),
        'total': _money(total),
    }


def calculate_invoice_totals(*, seller_state, place_of_supply_state, invoice_type, line_items) -> dict:
    """line_items: list of dicts with quantity/rate/discount_type/discount_value/tax_rate
    (plus any other keys the caller wants carried through, e.g. description - untouched).

    Returns computed per-line results under 'lines' (in the same order given)
    and the invoice-level totals. CGST+SGST applies when the seller's state
    matches the place of supply; otherwise the full rate goes to IGST.
    Bill of Supply / Non-GST invoices carry no tax at all, regardless of each
    line's tax_rate."""
    no_tax = invoice_type in NO_TAX_INVOICE_TYPES
    same_state = (
        not no_tax
        and (seller_state or '').strip().lower() == (place_of_supply_state or '').strip().lower()
    )
    tax_mode = 'none' if no_tax else ('split' if same_state else 'igst')

    lines = []
    subtotal = Decimal('0')
    discount_total = Decimal('0')
    taxable_amount = Decimal('0')
    tax_total = Decimal('0')

    for item in line_items:
        result = calculate_line(
            quantity=item['quantity'], rate=item['rate'],
            discount_type=item.get('discount_type', 'fixed'), discount_value=item.get('discount_value', 0),
            tax_rate=item.get('tax_rate', 0), invoice_type=invoice_type,
        )
        lines.append({**item, **result})
        subtotal += result['gross']
        discount_total += result['discount']
        taxable_amount += result['taxable']
        tax_total += result['tax']

    if tax_mode == 'split':
        cgst_total = _money(tax_total / 2)
        sgst_total = tax_total - cgst_total  # avoids a rounding-split mismatch vs tax_total
        igst_total = Decimal('0.00')
    elif tax_mode == 'igst':
        cgst_total = Decimal('0.00')
        sgst_total = Decimal('0.00')
        igst_total = tax_total
    else:
        cgst_total = sgst_total = igst_total = Decimal('0.00')

    grand_total = taxable_amount + cgst_total + sgst_total + igst_total

    return {
        'lines': lines,
        'tax_mode': tax_mode,
        'subtotal': _money(subtotal),
        'discount_total': _money(discount_total),
        'taxable_amount': _money(taxable_amount),
        'cgst_total': _money(cgst_total),
        'sgst_total': _money(sgst_total),
        'igst_total': _money(igst_total),
        'grand_total': _money(grand_total),
    }


_ONES = [
    '', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten',
    'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen',
]
_TENS = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']


def _three_digit_words(n: int) -> str:
    parts = []
    if n >= 100:
        parts.append(f"{_ONES[n // 100]} Hundred")
        n %= 100
    if n >= 20:
        tens_word = _TENS[n // 10]
        ones = n % 10
        parts.append(f"{tens_word}-{_ONES[ones]}" if ones else tens_word)
    elif n > 0:
        parts.append(_ONES[n])
    return ' '.join(parts)


def _integer_to_indian_words(n: int) -> str:
    if n == 0:
        return 'Zero'
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, hundred = divmod(n, 1_000)
    segments = []
    if crore:
        segments.append(f"{_three_digit_words(crore)} Crore")
    if lakh:
        segments.append(f"{_three_digit_words(lakh)} Lakh")
    if thousand:
        segments.append(f"{_three_digit_words(thousand)} Thousand")
    if hundred:
        segments.append(_three_digit_words(hundred))
    return ' '.join(segments)


def amount_in_words(value, currency_label='Rupees') -> str:
    """Indian numbering system (lakh/crore). E.g. 289100.50 ->
    'Rupees Two Lakh Eighty-Nine Thousand One Hundred and Fifty Paise Only'."""
    value = _money(value)
    rupees = int(value)
    paise = int((value - rupees) * 100)

    words = f"{currency_label} {_integer_to_indian_words(rupees)}"
    if paise:
        words += f" and {_integer_to_indian_words(paise)} Paise"
    return f"{words} Only"
