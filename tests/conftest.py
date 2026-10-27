import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    monkeypatch.setenv("MW83_DATA_DIR", str(d))
    monkeypatch.setenv("MW83_BACKUP_DIR", str(tmp_path / "backups"))
    return d


@pytest.fixture
def db(data_dir):
    from mw83 import paths
    from mw83.db import Database

    database = Database(paths.db_path())
    yield database
    database.close()


@pytest.fixture
def settings(db):
    from mw83.services.settings import Settings

    return Settings(db)


@pytest.fixture
def make_product(db):
    from mw83.services import catalog
    from mw83.services.catalog import ProductInput, VariantInput

    def _make(name="Classic Cotton Shirt", price=99900, cost=50000, mrp=129900, variants=None, **kw):
        cat = catalog.category_id_by_name(db, "Shirts")
        if variants is None:
            variants = [VariantInput(size="M", colour="Black", barcode="1000001", sku="CCS-M-BLK", opening_stock=10),
                        VariantInput(size="L", colour="Black", barcode="1000002", sku="CCS-L-BLK", opening_stock=5)]
        p = ProductInput(name=name, category_id=cat, price=price, cost=cost, mrp=mrp, variants=variants, **kw)
        pid = catalog.save_product(db, p)
        return catalog.get_product(db, pid)

    return _make


@pytest.fixture
def cart_line(db):
    from mw83.services import catalog
    from mw83.services.sales import line_from_variant

    def _line(code, qty=1, **kw):
        ln = line_from_variant(catalog.variant_by_code(db, code))
        ln.qty = qty
        for k, v in kw.items():
            setattr(ln, k, v)
        return ln

    return _line
