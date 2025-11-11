import React from 'react';

export default function Login() {
  return (
    <main style={{padding: '1rem'}}>
      <h1>Login</h1>
      <form>
        <label>Email<br/><input type="email" name="email" required /></label><br/><br/>
        <label>Password<br/><input type="password" name="password" required /></label><br/><br/>
        <button type="submit">Sign in</button>
      </form>
      <p><a href="/frontendtend/signup.html">Need an account? Sign up</a></p>
    </main>
  );
}
