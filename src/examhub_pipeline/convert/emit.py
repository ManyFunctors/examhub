"""Write an exam record as template-shaped TOML (decision 25 layout).

Tables and arrays of tables are indented two spaces per level; keys in each
block are aligned. Dicts keep their insertion order, which is the template's.
"""

import datetime as dt
import re

BARE = re.compile(r'^[A-Za-z0-9_-]+$')


def key(k):
    return k if BARE.match(k) else "'" + k.replace("'", "\\'") + "'"


def val(v):
    if isinstance(v, bool):
        raise TypeError('use yes/no strings, not booleans')
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, str):
        return "'" + v.replace("'", "’") + "'" if '\n' not in v else "'''" + v + "'''"
    if isinstance(v, (list, tuple)):
        return '[' + ', '.join(val(x) for x in v) + ']'
    raise TypeError(type(v))


def is_table(v):
    return isinstance(v, dict)


def is_table_array(v):
    return isinstance(v, list) and v and all(isinstance(x, dict) for x in v)


def block(d, path, out):
    pad = '  ' * (len(path) - 1)
    scalars = [(k, v) for k, v in d.items() if not is_table(v) and not is_table_array(v)]
    width = max((len(key(k)) for k, _ in scalars), default=0)
    for k, v in scalars:
        out.append(f'{pad}{key(k).ljust(width)} = {val(v)}')
    for k, v in d.items():
        sub = path + [key(k)]
        hpad = '  ' * (len(sub) - 1)
        if is_table(v):
            out.append('')
            out.append(f'{hpad}[{".".join(sub)}]')
            block(v, sub, out)
        elif is_table_array(v):
            for row in v:
                out.append('')
                out.append(f'{hpad}[[{".".join(sub)}]]')
                block(row, sub, out)


def dump(record, headings=None):
    """headings: {top-level key: comment line} printed before that section."""
    out = ['+++']
    top_scalars, rest = {}, {}
    for k, v in record.items():
        (rest if is_table(v) or is_table_array(v) else top_scalars)[k] = v
    # top-level scalars are grouped by the headings dict order
    groups = headings or {}
    width = max(len(key(k)) for k in top_scalars)
    for k, v in top_scalars.items():
        if k in groups:
            out.append('')
            out.append(f'# ═══ {groups[k]} ' + '═' * max(3, 64 - len(groups[k])))
        out.append(f'{key(k).ljust(width)} = {val(v)}')
    for k, v in rest.items():
        if k in groups:
            out.append('')
            out.append(f'# ═══ {groups[k]} ' + '═' * max(3, 64 - len(groups[k])))
        if is_table(v):
            out.append(f'[{key(k)}]')
            block(v, [key(k)], out)
        else:
            for row in v:
                out.append('')
                out.append(f'[[{key(k)}]]')
                block(row, [key(k)], out)
    out.append('+++')
    text = '\n'.join(out) + '\n'
    return re.sub(r'\n{3,}', '\n\n', text)
