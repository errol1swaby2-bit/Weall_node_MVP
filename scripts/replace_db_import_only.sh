set -euo pipefail
OLD='from weall_node.db.sqlite_dev import DB'
NEW='from weall_node.db.repo import DB'  # <-- change this target if needed

# Preview
echo "Will replace:"
echo "  $OLD"
echo "with:"
echo "  $NEW"
echo

# Run replacement across all .py files
find . -type f -name "*.py" -print0 \
| xargs -0 perl -0777 -i -pe "s#^\\Q${OLD}\\E\\s*\$#${NEW}#mg"
