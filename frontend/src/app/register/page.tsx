"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { apiRequest, errorDetail } from "@/services/api";

export default function RegisterPage() {
  const router = useRouter();

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleRegister(e: FormEvent) {
    e.preventDefault();

    setError("");
    setLoading(true);

    try {
      const response = await apiRequest("/api/auth/register", {
        method: "POST",
        body: JSON.stringify({
          name,
          email,
          password,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        setError(errorDetail(data, "Registration failed"));
        return;
      }

      router.push("/login");
    } catch {
      setError("Could not connect to backend");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen bg-black text-white flex items-center justify-center p-6">
      <div className="w-full max-w-md border border-zinc-800 bg-zinc-950 rounded-3xl p-8">
        <h1 className="text-3xl font-bold">Create account</h1>
        <p className="text-zinc-400 mt-2 mb-8">Start using AI Multitask</p>

        <form onSubmit={handleRegister} className="space-y-5">
          <div>
            <label htmlFor="register-name" className="text-sm text-zinc-300">
              Name
            </label>
            <input
              id="register-name"
              value={name}
              required
              onChange={(e) => setName(e.target.value)}
              placeholder="Your name"
              className="mt-2 w-full rounded-xl bg-zinc-900 border border-zinc-700 p-3"
            />
          </div>

          <div>
            <label htmlFor="register-email" className="text-sm text-zinc-300">
              Email
            </label>
            <input
              id="register-email"
              type="email"
              value={email}
              required
              onChange={(e) => setEmail(e.target.value)}
              placeholder="Email"
              className="mt-2 w-full rounded-xl bg-zinc-900 border border-zinc-700 p-3"
            />
          </div>

          <div>
            <label htmlFor="register-password" className="text-sm text-zinc-300">
              Password
            </label>
            <input
              id="register-password"
              type="password"
              value={password}
              required
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Password"
              className="mt-2 w-full rounded-xl bg-zinc-900 border border-zinc-700 p-3"
            />
          </div>

          {error && <p className="text-red-400">{error}</p>}

          <button
            disabled={loading}
            className="w-full bg-white text-black rounded-xl py-3 font-semibold"
          >
            {loading ? "Creating..." : "Create Account"}
          </button>
        </form>

        <p className="text-center text-zinc-400 mt-6">
          Already registered?{" "}
          <Link href="/login" className="text-white">
            Login
          </Link>
        </p>
      </div>
    </main>
  );
}
