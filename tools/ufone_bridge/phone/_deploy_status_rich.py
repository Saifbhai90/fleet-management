"""Deploy expanded detail_ops.py (phone status metrics) via Cloudflare."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.ufone_bridge.phone.phone_ssh import phone_exec_cf, phone_put_cf

detail = Path(__file__).resolve().parents[1].joinpath("detail_ops.py").read_bytes()
phone_put_cf(
    "/data/data/com.termux/files/home/ufone-bridge/detail_ops.py",
    detail,
    mode="644",
)
print("PUT", len(detail))

# Restart detail server only (worker keeps running). Schedule after remote-exec returns.
cmd = r"""
export HOME=/data/data/com.termux/files/home
export PATH=/data/data/com.termux/files/usr/bin:$PATH
nohup bash -c 'sleep 2; pkill -f "python detail_ops.py" || true; sleep 1; cd "$HOME/ufone-bridge" && nohup python detail_ops.py >>"$HOME/ufone-bridge/detail_ops.log" 2>&1 &' >/dev/null 2>&1 &
echo RESTART_SCHEDULED
"""
print(phone_exec_cf(cmd, timeout=30))
