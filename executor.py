@@
     def add_allowed_user(self, post_id: int, user_id: str):
         """Uploader grants explicit access to 'user_id' for a private post."""
         post = self.state["posts"].get(post_id)
-        if not post:
-            return False
-        post.setdefault("allowed_users", []).append(user_id)
-        return True
        if not post:
            return False
        post.setdefault("allowed_users", []).append(user_id)
        return True
