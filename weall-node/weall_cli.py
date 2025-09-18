# ==============================
# weall_cli.py (Updated)
# ==============================
from executor import WeAllExecutor, POH_REQUIREMENTS

def safe_int_input(prompt):
    try:
        return int(input(prompt))
    except ValueError:
        print("Invalid input, expected a number.")
        return None

def run_cli():
    executor = WeAllExecutor(poh_requirements=POH_REQUIREMENTS)
    print("WeAll CLI started. Type 'exit' to quit.")

    while True:
        cmd = input(
            "\nCommand (register/propose/vote/post/comment/edit_post/delete_post/edit_comment/delete_comment/"
            "list_user_posts/list_tag_posts/show_post/show_posts/report_post/report_comment/"
            "create_dispute/juror_vote/like_post/deposit/transfer/balance/allocate_treasury/reclaim_treasury/"
            "send_message/read_messages/exit): "
        ).strip().lower()

        if cmd == "exit":
            break

        # ------------------------
        # User Management
        # ------------------------
        elif cmd == "register":
            user = input("User ID: ")
            poh = safe_int_input("PoH Level: ")
            result = executor.register_user(user, poh_level=poh)
            print(result)

        elif cmd == "add_friend":
            uid = input("User ID: ")
            fid = input("Friend ID: ")
            print(executor.add_friend(uid, fid))

        elif cmd == "create_group":
            uid = input("User ID: ")
            group_name = input("Group name: ")
            members = input("Member IDs (comma-separated, optional): ")
            member_list = members.split(",") if members else None
            print(executor.create_group(uid, group_name, member_list))

        # ------------------------
        # Posts / Comments
        # ------------------------
        elif cmd == "post":
            uid = input("User ID: ")
            content = input("Post content: ")
            tags = input("Tags (comma-separated, optional): ").split(",") if input("Add tags? (y/n): ").lower() == "y" else None
            print(executor.create_post(uid, content, tags))

        elif cmd == "comment":
            uid = input("User ID: ")
            pid = safe_int_input("Post ID: ")
            content = input("Comment content: ")
            tags = input("Tags (comma-separated, optional): ").split(",") if input("Add tags? (y/n): ").lower() == "y" else None
            print(executor.create_comment(uid, pid, content, tags))

        elif cmd == "edit_post":
            uid = input("User ID: ")
            pid = safe_int_input("Post ID: ")
            new_content = input("New post content: ")
            print(executor.edit_post(uid, pid, new_content))

        elif cmd == "delete_post":
            uid = input("User ID: ")
            pid = safe_int_input("Post ID: ")
            print(executor.delete_post(uid, pid))

        elif cmd == "edit_comment":
            uid = input("User ID: ")
            cid = safe_int_input("Comment ID: ")
            new_content = input("New comment content: ")
            print(executor.edit_comment(uid, cid, new_content))

        elif cmd == "delete_comment":
            uid = input("User ID: ")
            cid = safe_int_input("Comment ID: ")
            print(executor.delete_comment(uid, cid))

        elif cmd == "like_post":
            uid = input("User ID: ")
            pid = safe_int_input("Post ID: ")
            print(executor.like_post(uid, pid))

        # ------------------------
        # Governance / Proposals
        # ------------------------
        elif cmd == "propose":
            uid = input("User ID: ")
            title = input("Proposal title: ")
            desc = input("Proposal description: ")
            pallet = input("Pallet reference: ")
            print(executor.propose(uid, title, desc, pallet))

        elif cmd == "vote":
            uid = input("User ID: ")
            pid = safe_int_input("Proposal ID: ")
            option = input("Vote option: ")
            print(executor.vote(uid, pid, option))

        # ------------------------
        # Disputes / Juror Voting
        # ------------------------
        elif cmd == "create_dispute":
            uid = input("Reporter ID: ")
            pid = safe_int_input("Target Post ID: ")
            desc = input("Dispute description: ")
            print(executor.create_dispute(uid, pid, desc))

        elif cmd == "juror_vote":
            uid = input("Juror ID: ")
            did = safe_int_input("Dispute ID: ")
            vote_option = input("Vote option: ")
            print(executor.juror_vote(uid, did, vote_option))

        elif cmd == "report_post":
            uid = input("Reporter ID: ")
            pid = safe_int_input("Post ID: ")
            desc = input("Report description: ")
            print(executor.report_post(uid, pid, desc))

        elif cmd == "report_comment":
            uid = input("Reporter ID: ")
            cid = safe_int_input("Comment ID: ")
            desc = input("Report description: ")
            print(executor.report_comment(uid, cid, desc))

        # ------------------------
        # Treasury
        # ------------------------
        elif cmd == "allocate_treasury":
            pool = input("Pool name: ")
            amt = safe_int_input("Amount: ")
            print(executor.allocate_treasury(pool, amt))

        elif cmd == "reclaim_treasury":
            pool = input("Pool name: ")
            amt = safe_int_input("Amount: ")
            print(executor.reclaim_treasury(pool, amt))

        # ------------------------
        # Ledger / Transfers
        # ------------------------
        elif cmd == "deposit":
            uid = input("User ID: ")
            amt = safe_int_input("Amount: ")
            executor.state["treasury"][uid] += amt
            print(f"{amt} deposited to {uid}'s treasury account")

        elif cmd == "transfer":
            from_user = input("From user: ")
            to_user = input("To user: ")
            amt = safe_int_input("Amount: ")
            # Simplified; add more ledger logic if needed
            if executor.state["treasury"].get(from_user, 0) >= amt:
                executor.state["treasury"][from_user] -= amt
                executor.state["treasury"][to_user] += amt
                print("Transfer successful")
            else:
                print("Transfer failed")

        elif cmd == "balance":
            uid = input("User ID: ")
            bal = executor.state["treasury"].get(uid, 0)
            print(f"{uid} balance: {bal}")

        # ------------------------
        # Messaging
        # ------------------------
        elif cmd == "send_message":
            sender = input("From user: ")
            recipient = input("To user: ")
            msg = input("Message text: ")
            print(executor.send_message(sender, recipient, msg))

        elif cmd == "read_messages":
            uid = input("User ID: ")
            msgs = executor.read_messages(uid)
            for m in msgs:
                print(f"From {m['from']} | {m['timestamp']}: {m['text']}")

        # ------------------------
        # Posts / Display
        # ------------------------
        elif cmd == "list_user_posts":
            uid = input("User ID: ")
            posts = [pid for pid, p in executor.state["posts"].items() if p["user"] == uid]
            print(f"Posts by {uid}: {posts}")

        elif cmd == "list_tag_posts":
            tag = input("Tag to search: ")
            posts = [pid for pid, p in executor.state["posts"].items() if tag in p.get("tags", [])]
            print(f"Posts with tag '{tag}': {posts}")

        elif cmd == "show_post":
            pid = safe_int_input("Post ID: ")
            post = executor.state["posts"].get(pid)
            print(post if post else f"Post {pid} not found.")

        elif cmd == "show_posts":
            for pid, post in executor.state["posts"].items():
                print(f"{pid}: {post}")

        else:
            print("Unknown command.")


if __name__ == "__main__":
    run_cli()
