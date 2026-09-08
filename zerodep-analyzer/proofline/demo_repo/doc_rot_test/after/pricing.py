
def calculate_discount(price: float, pct: float) -> float:
    """Return price after applying a percentage discount.

    Args:
        price: Original item price.
        pct: Discount percentage (0-100).

    Returns:
        float: Discounted price.
    """
    return round(price * (1 - pct / 100), 2)
