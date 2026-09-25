"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function HomePage() {
  const router = useRouter();

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    router.replace(token ? "/chat" : "/login");
  }, [router]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-zinc-950 text-white">
      Redirecting...
    </main>
  );
}
