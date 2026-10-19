"""ORM rows <-> the `Catalog` aggregate. ORM objects never leave the `database` package."""

from collections.abc import Iterable

from src.database.models import Payee as PayeeRow
from src.database.models import PaymentSource as SourceRow
from src.database.models import StoreProduct as ProductRow
from src.domain.catalog import Catalog, Payee, PaymentSource, Product
from src.domain.enums import PaymentSourceKind, ProductCategory


def to_catalog(
    user_id: int,
    payee_rows: Iterable[PayeeRow],
    source_rows: Iterable[SourceRow],
    product_rows: Iterable[ProductRow],
) -> Catalog:
    catalog = Catalog(user_id=user_id)
    key_by_payee_id: dict[int, str] = {}
    for row in payee_rows:
        key_by_payee_id[row.id] = row.payee_key
        catalog.payees[row.payee_key] = Payee(
            id=row.id,
            payee_key=row.payee_key,
            name=row.name,
            legal_name=row.legal_name,
            tax_id=row.tax_id,
            address=row.address,
        )
    for source in source_rows:
        catalog.payment_sources[source.id] = PaymentSource(
            id=source.id,
            kind=PaymentSourceKind(source.kind),
            name=source.name,
            brand=source.brand,
            last4=source.last4,
        )
    for row in product_rows:
        catalog.products[row.product_key] = Product(
            id=row.id,
            payee_key=key_by_payee_id[row.payee_id],
            product_key=row.product_key,
            name_raw=row.name_raw,
            name=row.name,
            category=ProductCategory(row.category),
            unit=row.unit,
            created_by_receipt_id=row.created_by_receipt_id,
            source_ref=row.source_ref,
        )
    return catalog


def to_payee_row(user_id: int, payee: Payee) -> PayeeRow:
    return PayeeRow(
        user_id=user_id,
        payee_key=payee.payee_key,
        name=payee.name,
        legal_name=payee.legal_name,
        tax_id=payee.tax_id,
        address=payee.address,
    )


def to_source_row(user_id: int, source: PaymentSource) -> SourceRow:
    return SourceRow(
        user_id=user_id,
        kind=str(source.kind),  # the database CHECK decides what is valid
        name=source.name,
        brand=source.brand,
        last4=source.last4,
    )


def to_product_row(user_id: int, payee_id: int, product: Product) -> ProductRow:
    return ProductRow(
        user_id=user_id,
        payee_id=payee_id,
        product_key=product.product_key,
        name_raw=product.name_raw,
        name=product.name,
        category=str(product.category),  # the database CHECK decides what is valid
        unit=product.unit,
        created_by_receipt_id=product.created_by_receipt_id,
        source_ref=product.source_ref,
    )
