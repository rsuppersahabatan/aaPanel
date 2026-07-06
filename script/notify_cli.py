#coding: utf-8
# -------------------------------------------------------------------
# aapanel - agent notification CLI
# Standalone entry that sends a notification via mod/base/push_mod channels.
# Call directly for an immediate notify, or from a cron task for scheduled ones:
#   btpython /www/server/panel/script/notify_cli.py --title "..." --message "..." --channels mail,discord
#
# send_notify() is the single source of truth for the sending logic - it is also
# imported by the agent Notify tool (panel_tools.Notify), so the CLI and the tool
# never diverge.
# -------------------------------------------------------------------
import sys
import os
import argparse


def send_notify(title, message, channels=None):
    """Send a notification to all enabled non-sms push channels.
    channels: optional list of sender_type (e.g. ['mail','discord']); None = all enabled.
    Returns a list of per-channel dicts {channel, ok, error}.
    Caller must ensure panel root is on sys.path (so mod.base.* is importable)."""
    from mod.base.push_mod.mods import SenderConfig
    from mod.base.push_mod.system import PushSystem
    ps = PushSystem()
    wanted = set(channels) if channels else None
    results = []
    for s in SenderConfig().config:
        if not s.get("used"):
            continue
        st = s.get("sender_type")
        if st == "sms":  # sms uses a template mechanism, not free text
            continue
        if wanted is not None and st not in wanted:
            continue
        try:
            res = ps.sender_cls(st)(s).send_msg(msg=message, title=title)
            results.append({"channel": st, "ok": not isinstance(res, str),
                            "error": res if isinstance(res, str) else None})
        except Exception as e:
            results.append({"channel": st, "ok": False, "error": str(e)})
    return results


def main():
    # Panel runtime environment - only needed when run as a standalone script.
    os.chdir('/www/server/panel')
    sys.path.insert(0, '/www/server/panel')
    sys.path.insert(0, 'class/')
    sys.path.insert(0, 'class_v2/')

    parser = argparse.ArgumentParser(description="Send a notification via configured push channels.")
    parser.add_argument("--title", required=True, help="Notification title")
    parser.add_argument("--message", required=True, help="Notification body (markdown supported by most channels)")
    parser.add_argument("--channels", default="",
                        help="Comma-separated sender_type list, e.g. 'mail,discord'. Empty = all enabled non-sms channels")
    args = parser.parse_args()

    channels = [c.strip() for c in args.channels.split(",") if c.strip()] or None
    # Shell double-quotes don't parse \n/\t; convert literal escapes so a cron sBody like
    # --message "line1\nline2" renders as two lines (Notify tool passes real newlines, unaffected).
    message = args.message.replace('\\n', '\n').replace('\\t', '\t')
    results = send_notify(args.title, message, channels)
    sent = sum(1 for r in results if r["ok"])
    print("notify sent %d/%d channels" % (sent, len(results)))
    for r in results:
        print("  - %s: %s" % (r["channel"], "ok" if r["ok"] else "fail: %s" % r.get("error")))
    sys.exit(0 if sent > 0 else 1)


if __name__ == "__main__":
    main()
