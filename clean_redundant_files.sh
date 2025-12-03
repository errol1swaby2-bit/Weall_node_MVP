#!/data/data/com.termux/files/usr/bin/bash
# WeAll Node cleanup script for Termux/Linux
# Safely removes redundant or outdated files while preserving active code.

set -e

echo "🧹 Starting cleanup in $(pwd)"

# -------------------------------------------------------
# 1. Define core keep list (essential project files)
# -------------------------------------------------------
KEEP_DIRS=("weall_node" "tests")
KEEP_FILES=("README.md" "requirements.txt" "Dockerfile" "weall_export.pdf")

# -------------------------------------------------------
# 2. Remove known redundant executors and patches
# -------------------------------------------------------
echo "🗑️  Removing old executors and patch files..."
find . -type f \( \
    -name "executor_old.py" -o \
    -name "weall_executor_backup.py" -o \
    -name "executor.py" -o \
    -name "apply_weall_patch.py" -o \
    -name "apply_weall_prod.sh" -o \
    -name "*.patch" -o \
    -name "*.pub" -o \
    -name "*.bak" -o \
    -name "*.tmp" -o \
    -name "*.json" -o \
    -name "*.zip" -o \
    -name "*.tar.gz" -o \
    -name "*.log" \
    \) -not -path "./weall_node/*" -exec rm -f {} \; 2>/dev/null || true

# -------------------------------------------------------
# 3. Remove legacy app_state and sim directories
# -------------------------------------------------------
echo "🗑️  Removing legacy app_state, sim, and patch dirs..."
rm -rf weall_node/app_state 2>/dev/null || true
rm -rf sim 2>/dev/null || true
rm -rf patches 2>/dev/null || true

# -------------------------------------------------------
# 4. Remove compiled caches and Python artifacts
# -------------------------------------------------------
echo "🧠 Removing __pycache__ and test caches..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true

# -------------------------------------------------------
# 5. Remove old PDFs, patch exports, and backups
# -------------------------------------------------------
echo "🗑️  Removing old exports..."
find . -type f \( -name "weall_export*.pdf" -o -name "*.orig" \) -delete 2>/dev/null || true

# -------------------------------------------------------
# 6. Verify structure
# -------------------------------------------------------
echo "✅ Cleanup complete. Remaining structure:"
tree -L 2 weall_node 2>/dev/null || ls -R weall_node

echo ""
echo "🧩 Preserved modules:"
echo "   - weall_node/weall_executor.py"
echo "   - weall_node/weall_api.py"
echo "   - weall_node/governance.py"
echo "   - weall_node/weall_runtime_gov_cli.py"
echo "   - weall_node/__init__.py"
echo "   - weall_node/weall_config.yaml"
echo ""
echo "✨ Ready for fresh commit."
