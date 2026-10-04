"""Storage locations (vaults, rooms, lockers, labs). Administrators only.
Locations are never deleted: custody history refers to them. A location
that is no longer used is deactivated, which stops new transfers to it
(sp_transfer_evidence refuses inactive locations)."""
from .. import audit
from ..db import ConstraintViolation, query_all, query_one, transaction

LOCATION_TYPES = ("Vault", "Evidence Room", "Examination Lab", "Imaging Bench", "Other")


class LocationError(Exception):
    pass


def list_locations():
    return query_all(
        """
        SELECT sl.location_id, sl.location_name, sl.location_type, sl.description, sl.is_active,
               (SELECT COUNT(*) FROM evidence e WHERE e.current_location_id = sl.location_id) AS items_here,
               (SELECT COUNT(*) FROM chain_of_custody coc WHERE coc.location_id = sl.location_id) AS custody_entries
          FROM storage_locations sl
         ORDER BY sl.is_active DESC, sl.location_type, sl.location_name
        """
    )


def get_location(location_id):
    return query_one("SELECT location_id, location_name, location_type, description, is_active "
                     "FROM storage_locations WHERE location_id = %s", (location_id,))


def _name_taken(err):
    return isinstance(err, ConstraintViolation) and err.constraint == "uq_locations_name"


def create_location(name, location_type, description):
    try:
        with transaction() as cur:
            cur.execute("INSERT INTO storage_locations (location_name, location_type, description) VALUES (%s, %s, %s)",
                        (name, location_type, description or None))
            audit.record("location.create", "Storage location", name, cursor=cur, details=location_type)
    except ConstraintViolation as err:
        if _name_taken(err):
            raise LocationError("A location with that name already exists.") from err
        raise


def update_location(location_id, name, location_type, description):
    try:
        with transaction() as cur:
            cur.execute("SELECT location_name, location_type, description FROM storage_locations "
                        "WHERE location_id = %s FOR UPDATE", (location_id,))
            old = cur.fetchone()
            if old is None:
                raise LocationError("Location not found.")
            changes = []
            if name != old["location_name"]:
                changes.append(f"renamed from {old['location_name']}")
            if location_type != old["location_type"]:
                changes.append(f"type {old['location_type']} to {location_type}")
            if (description or None) != old["description"]:
                changes.append("description")
            if not changes:
                return False
            cur.execute("UPDATE storage_locations SET location_name = %s, location_type = %s, description = %s "
                        "WHERE location_id = %s", (name, location_type, description or None, location_id))
            audit.record("location.update", "Storage location", name, cursor=cur, details="; ".join(changes))
    except ConstraintViolation as err:
        if _name_taken(err):
            raise LocationError("A location with that name already exists.") from err
        raise
    return True


def set_active(location_id, active):
    with transaction() as cur:
        cur.execute("SELECT location_name, is_active FROM storage_locations WHERE location_id = %s FOR UPDATE",
                    (location_id,))
        row = cur.fetchone()
        if row is None:
            raise LocationError("Location not found.")
        if bool(row["is_active"]) == active:
            raise LocationError("The location is already " + ("active." if active else "inactive."))
        cur.execute("UPDATE storage_locations SET is_active = %s WHERE location_id = %s", (active, location_id))
        audit.record("location.activate" if active else "location.deactivate", "Storage location",
                     row["location_name"], cursor=cur)
