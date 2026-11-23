from contextforge.access_control.models import AccessFilter
from contextforge.common.hashing import chunk_id_for
from contextforge.common.models import Chunk, Hit

ADMIN = AccessFilter("acme", "root", ("administrator",), unrestricted_in_tenant=True)
ENG = AccessFilter("acme", "bob", ("engineering",))
EMP = AccessFilter("acme", "erin", ("general_employee",))
OTHER_TENANT = AccessFilter("other", "zed", ("administrator",), unrestricted_in_tenant=True)


def make_chunk(doc="d1", version=1, index=0, text="hello", title=None, groups=("engineering",),
               tenant="acme", owner="o", page=None, path="a.md"):
    return Chunk(chunk_id_for(doc, version, index), doc, version, index, text, title, page, path,
                 tenant, owner, list(groups))


def make_hit(cid, score=0.0):
    return Hit(cid, "d", 1, 0, cid, None, None, "p", "acme", score)
