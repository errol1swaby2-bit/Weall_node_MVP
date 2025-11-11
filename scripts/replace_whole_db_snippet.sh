set -euo pipefail
NEW_IMPORT='from weall_node.db.repo import DB'  # <-- set destination

pattern='from weall_node\.db\.sqlite_dev import DB\s*\n# create tables at startup \(simple example\)\s*\n# await DB\.execute\("CREATE TABLE IF NOT EXISTS users \(id INTEGER PRIMARY KEY, email TEXT UNIQUE\)"\)\s*\n\n# insert\s*\n# user_id = await DB\.execute\("INSERT INTO users\(email\) VALUES\(\?\)", email\)\s*\n\n# select\s*\n# me = await DB\.query_one\("SELECT \* FROM users WHERE email=\?", email\)\s*'

find . -type f -name '*.py' -print0 \
| xargs -0 perl -0777 -i -pe "s/${pattern}/${NEW_IMPORT}\n/g"
