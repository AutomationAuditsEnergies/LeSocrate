import re
import unicodedata


def slugify(value, fallback="item", max_length=64):
    """Return a stable ASCII slug for URLs and DB lookup."""
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")
    slug = slug[:max_length].strip("-")
    return slug or fallback


def unique_slug(cursor, table, base_slug, *, column="slug", scope_column=None, scope_value=None, exclude_id=None):
    """Return a slug unique in table, optionally inside a tenant scope."""
    slug = base_slug
    suffix = 2
    while True:
        where = [f"{column} = ?"]
        params = [slug]
        if scope_column is not None:
            if scope_value is None:
                where.append(f"{scope_column} IS NULL")
            else:
                where.append(f"{scope_column} = ?")
                params.append(scope_value)
        if exclude_id is not None:
            where.append("id != ?")
            params.append(exclude_id)
        cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE {' AND '.join(where)}", params)
        if cursor.fetchone()[0] == 0:
            return slug
        slug = f"{base_slug}-{suffix}"
        suffix += 1
