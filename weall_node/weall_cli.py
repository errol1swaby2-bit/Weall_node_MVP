#!/usr/bin/env python3
"""
WeAll CLI — Self-Amending + Mempool/Validator
"""
from executor import WeAllExecutor

POH_REQUIREMENTS = {
    "propose": 3,
    "vote": 2,
    "post": 2,
    "comment": 2,
    "dispute": 3,
    "juror": 3,
}


def safe_int(prompt):
    try:
        return int(input(prompt))
    except:
        print("Invalid number")
        return None


def run_cli():
    ex = WeAllExecutor(
        dsl_file="weall_dsl_v0.5.yaml", poh_requirements=POH_REQUIREMENTS
    )
    print("WeAll CLI started. Type 'exit' to quit.")

    while True:
        cmd = (
            input(
                "\nCommand (register/post/comment/balance/transfer/advance_epoch/"
                "propose_code_update/vote_proposal/close_proposal/enact_proposal/"
                "list_proposals/show_proposal/select_validator/validate_mempool/"
                "send_message/read_messages/exit): "
            )
            .strip()
            .lower()
        )

        if cmd == "exit":
            ex.stop()
            break

        elif cmd == "register":
            u = input("User ID: ").strip()
            poh = safe_int("PoH Level (1-3): ")
            if poh is None:
                continue
            print(ex.register_user(u, poh_level=poh))

        elif cmd == "post":
            u = input("User ID: ").strip()
            c = input("Post content: ")
            tags = input("Tags (csv, optional): ").strip()
            tags = [t.strip() for t in tags.split(",")] if tags else None
            print(ex.create_post(u, c, tags))

        elif cmd == "comment":
            u = input("User ID: ").strip()
            pid = safe_int("Post ID: ")
            if pid is None:
                continue
            c = input("Comment content: ")
            tags = input("Tags (csv, optional): ").strip()
            tags = [t.strip() for t in tags.split(",")] if tags else None
            print(ex.create_comment(u, pid, c, tags))

        elif cmd == "balance":
            u = input("User ID: ").strip()
            print({"balance": ex.ledger.balance(u)})

        elif cmd == "transfer":
            a = input("From user: ").strip()
            b = input("To user: ").strip()
            amt = safe_int("Amount: ")
            if amt is None:
                continue
            print({"ok": ex.ledger.transfer(a, b, amt)})

        elif cmd == "advance_epoch":
            print(ex.advance_epoch(force=True))

        # --- Governance ---
        elif cmd == "propose_code_update":
            u = input("User ID: ").strip()
            m = input("Module relpath (e.g., weall_node/executor.py): ").strip()
            h = input("IPFS hash of new file content: ").strip()
            s = input("SHA256 checksum (64 hex): ").strip().lower()
            d = input("Short description (optional): ").strip()
            print(ex.propose_code_update(u, m, h, s, description=d))

        elif cmd == "vote_proposal":
            u = input("User ID: ").strip()
            pid = safe_int("Proposal ID: ")
            if pid is None:
                continue
            v = input("Vote (yes/no/abstain): ").strip().lower()
            print(ex.vote_on_proposal(u, pid, v))

        elif cmd == "close_proposal":
            pid = safe_int("Proposal ID: ")
            if pid is None:
                continue
            print(ex.close_proposal(pid))

        elif cmd == "enact_proposal":
            u = input("Enactor (Tier-3) User ID: ").strip()
            pid = safe_int("Proposal ID: ")
            if pid is None:
                continue
            print(ex.try_enact_proposal(u, pid))

        elif cmd == "list_proposals":
            props = [
                ex.state["proposals"][k] for k in sorted(ex.state["proposals"].keys())
            ]
            for p in props:
                print(
                    f"[{p['id']}] {p['type']} {p['module']} — {p['status']} votes={len(p['votes'])}"
                )
            if not props:
                print("No proposals.")

        elif cmd == "show_proposal":
            pid = safe_int("Proposal ID: ")
            if pid is None:
                continue
            print(ex.state["proposals"].get(pid))

        # --- Validator / Chain ---
        elif cmd == "select_validator":
            print({"selected": ex.select_validator()})

        elif cmd == "validate_mempool":
            vid = input("Validator ID (Tier-3): ").strip()
            print(ex.validate_mempool(vid))

        # --- Messaging ---
        elif cmd == "send_message":
            a = input("From user: ").strip()
            b = input("To user: ").strip()
            msg = input("Message: ").strip()
            print(ex.send_message(a, b, msg))

        elif cmd == "read_messages":
            u = input("User ID: ").strip()
            for m in ex.read_messages(u):
                print(f"From {m['from']} | {m['ts']}: {m['text']}")

        else:
            print("Unknown command.")


if __name__ == "__main__":
    run_cli()
