"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Markdown from "@/components/Markdown";

import { apiRequest, errorDetail, responseError, SessionExpiredError } from "@/services/api";

type ChatItem = {
  is_pinned: boolean;
  is_archived: boolean;
  id: number;
  title: string;
  user_id: number;
  created_at: string;
  updated_at: string;
};

type MessageItem = {
  task_run_id?: number | null;
  id: number;
  chat_id: number;
  role: string;
  content: string;
  status: string;
  created_at: string;
};

type TaskItem = {
  run_id: number | null;
  result: string | null;
  error: string | null;
  id: number;
  chat_id: number;
  title: string;
  description: string | null;
  status: string;
  progress: number;
  order: number;
  created_at: string;
  updated_at: string;
};

function taskStatusLabel(status: string) {
  return status === "in_progress" ? "IN_PROGRESS" : status.toUpperCase();
}

function isGenericChatTitle(title: string | null | undefined) {
  if (!title) return true;

  const normalized = title.trim().toLowerCase();
  const cleaned = normalized.replace(/^new\s+/, "").trim();

  return ["", "chat", "new chat", "untitled chat", "new conversation", "new topic"].includes(cleaned);
}

function generateChatTitle(prompt: string) {
  const cleaned = prompt
    .replace(/[^a-zA-Z0-9\s?]/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  if (!cleaned) {
    return "New Chat";
  }

  const lower = cleaned.toLowerCase();
  let title = cleaned;

  if (lower.startsWith("what is ")) {
    title = cleaned.slice("what is ".length);
    title = `${title} Basics`;
  } else if (lower.startsWith("what are ")) {
    title = cleaned.slice("what are ".length);
    title = `${title} Basics`;
  } else if (lower.startsWith("how do i ")) {
    title = cleaned.slice("how do i ".length);
  } else if (lower.startsWith("can you explain ")) {
    title = cleaned.slice("can you explain ".length);
  } else if (lower.startsWith("explain ")) {
    title = cleaned.slice("explain ".length);
  } else if (lower.startsWith("tell me about ")) {
    title = cleaned.slice("tell me about ".length);
  }

  title = title.replace(/^new\s+/i, "").trim();

  if (!title) {
    return "New Chat";
  }

  const words = title
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 5)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase());

  const result = words.join(" ");
  return result.length > 40 ? `${result.slice(0, 37).trim()}...` : result;
}

export default function ChatPage() {
  const router = useRouter();
  const [chats, setChats] = useState<ChatItem[]>([]);
  const [selectedChatId, setSelectedChatId] = useState<number | null>(null);
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const [newChatTitle, setNewChatTitle] = useState("New Chat");
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [menuOpenChatId, setMenuOpenChatId] = useState<number | null>(null);
  const [renameChatId, setRenameChatId] = useState<number | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const nextTemporaryId = useRef(-1);
  const [abortController, setAbortController] = useState<AbortController | null>(null);
  const [tasks, setTasks] = useState<TaskItem[]>([]);

  const [newTaskTitle, setNewTaskTitle] = useState("");
  const [taskPrompt, setTaskPrompt] = useState("");
  const [taskBusy, setTaskBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [deletingResponse, setDeletingResponse] = useState(false);
  const [attachment, setAttachment] = useState<{ id: number; filename: string; text: string } | null>(null);
  const selectedId = useRef<number | null>(null);
  const hasRunningTasks = tasks.some(task => task.status === "in_progress");
  const busy = isStreaming || taskBusy || uploading || hasRunningTasks || deletingResponse;
  const [searchDraft, setSearchDraft] = useState("");
  const [query, setQuery] = useState("");
  const [archivedView, setArchivedView] = useState(false);
  const [editingMessage, setEditingMessage] = useState<MessageItem | null>(null);
  const [editText, setEditText] = useState("");
  const [copiedMessageId, setCopiedMessageId] = useState<number | null>(null);

  async function copyAnswer(message: MessageItem) {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopiedMessageId(message.id);
    } catch {
      setError("Could not copy automatically. Select the answer text and copy it manually.");
    }
  }

  async function updateChatFlags(chat: ChatItem, flags: { is_pinned?: boolean; is_archived?: boolean }) {
    try {
      const response = await apiRequest(`/api/chats/${chat.id}`, { method: "PATCH", body: JSON.stringify(flags) });
      if (!response.ok) throw await responseError(response, "Unable to update chat");
      const next = await response.json();
      setChats(current => current.map(c => c.id === chat.id ? next : c).filter(c => c.is_archived === archivedView)
        .sort((a, b) => Number(b.is_pinned) - Number(a.is_pinned) || b.updated_at.localeCompare(a.updated_at)));
      if (flags.is_archived !== undefined && selectedChatId === chat.id) {
        selectedId.current = null; setSelectedChatId(null); setMessages([]); setTasks([]);
      }
      setMenuOpenChatId(null);
    } catch (err) { setError(err instanceof Error ? err.message : "Unable to update chat"); }
  }

  async function cancelTasks() {
    if (!selectedChatId) return;
    try {
      const response = await apiRequest(`/api/chats/${selectedChatId}/tasks/cancel`, { method: "POST" });
      if (!response.ok) throw await responseError(response, "Unable to cancel tasks");
      await loadTasks(selectedChatId); await loadMessages(selectedChatId);
    } catch (err) { setError(err instanceof Error ? err.message : "Unable to cancel tasks"); }
  }

  async function saveMessageEdit() {
    if (!editingMessage || !editText.trim()) return;
    if (editingMessage.role === "user") {
      const assistant = messages.find(m => m.id > editingMessage.id && m.role === "assistant");
      if (!assistant) return;
      setEditingMessage(null);
      await runResponse(assistant, "edit", { id: editingMessage.id, content: editText });
    } else {
      try {
        const response = await apiRequest(`/api/chats/${editingMessage.chat_id}/messages/${editingMessage.id}`, {
          method: "PATCH", body: JSON.stringify({ content: editText }),
        });
        if (!response.ok) throw await responseError(response, "Unable to edit answer");
        setEditingMessage(null); await loadMessages(editingMessage.chat_id);
      } catch (err) { setError(err instanceof Error ? err.message : "Unable to edit answer"); }
    }
  }

  useEffect(() => {
    if (!selectedChatId || !hasRunningTasks || taskBusy) return;
    const chatId = selectedChatId;
    const interval = window.setInterval(() => {
      void apiRequest(`/api/chats/${chatId}/tasks`).then(async response => {
        if (response.ok) {
          const rows = await response.json();
          if (selectedId.current === chatId) {
            setTasks(rows);
            const history = await apiRequest(`/api/chats/${chatId}/messages`);
            if (history.ok) { const data = await history.json(); if (selectedId.current === chatId) setMessages(data); }
          }
        }
      }).catch(() => undefined);
    }, 1500);
    return () => window.clearInterval(interval);
  }, [selectedChatId, hasRunningTasks, taskBusy]);

  async function uploadFile(file: File) {
    setUploading(true);
    setError("");
    try {
      if (file.size > 5 * 1024 * 1024) throw new Error("File exceeds the 5 MB limit.");
      const body = new FormData();
      body.append("file", file);
      if (selectedChatId) body.append("chat_id", String(selectedChatId));
      const response = await apiRequest("/api/files/extract", { method: "POST", body });
      const data = await response.json();
      if (!response.ok) throw new Error(errorDetail(data, "Unable to read file"));
      setAttachment(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally { setUploading(false); }
  }

  async function handleTaskAction(action: "plan" | "run", taskId?: number, runId?: number) {
    if (!selectedChatId || busy) return;
    const chatId = selectedChatId;
    setTaskBusy(true);
    setError("");
    const poll = window.setInterval(() => { void Promise.all([loadTasks(chatId), loadMessages(chatId)]).catch(() => undefined); }, 1000);
    try {
      const response = await apiRequest(taskId ? `/api/chats/${chatId}/tasks/${taskId}/retry` : `/api/chats/${chatId}/tasks/${action}${runId ? `?run_id=${runId}` : ""}`, {
        method: "POST",
        body: action === "plan" ? JSON.stringify({ prompt: taskPrompt.trim(), attachment_ids: attachment ? [attachment.id] : [] }) : undefined,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(errorDetail(data, "Task request failed"));
      if (action === "plan") { setTaskPrompt(""); setAttachment(null); }
      await loadTasks(chatId);
      await loadMessages(chatId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Task request failed");
    } finally { window.clearInterval(poll); setTaskBusy(false); }
  }

  async function loadMessages(chatId: number) {
    const response = await apiRequest(`/api/chats/${chatId}/messages`);
    if (!response.ok) {
      throw await responseError(response, "Unable to load messages");
    }

    const data = await response.json();
    if (selectedId.current === chatId) setMessages(data);
  }

  async function loadTasks(chatId: number) {
    const response = await apiRequest(`/api/chats/${chatId}/tasks`);
    if (!response.ok) {
      throw await responseError(response, "Unable to load tasks");
    }

    const data = await response.json();
    if (selectedId.current === chatId) setTasks(data);
  }

  async function handleCreateTask() {
    if (!selectedChatId || !newTaskTitle.trim() || busy) {
      return;
    }

    try {
      const response = await apiRequest(`/api/chats/${selectedChatId}/tasks`, {
        method: "POST",
        body: JSON.stringify({
          title: newTaskTitle.trim(),
          description: newTaskTitle.trim(),
          attachment_ids: attachment ? [attachment.id] : [],
          status: "pending",
          progress: 0,
          order: tasks.length,
        }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || "Unable to create task");
      }

      const data = await response.json();
      setTasks((current) => [...current, data]);
      setNewTaskTitle("");
      setAttachment(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create task");
    }
  }

  async function handleCreateChat(e: FormEvent) {
    e.preventDefault();
    if (busy) return;

    try {
      const response = await apiRequest("/api/chats", {
        method: "POST",
        body: JSON.stringify({ title: newChatTitle || "New Chat" }),
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Unable to create chat");
      }

      const nextChats = [data, ...chats];
      setChats(nextChats);
      selectedId.current = data.id;
      setSelectedChatId(data.id);
      setMessages([]);
      setTasks([]);
      setAttachment(null);
      setNewChatTitle("New Chat");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create chat");
    }
  }

  async function handleRenameChat(chatId: number, currentTitle: string) {
    const trimmed = renameDraft.trim();
    if (!trimmed || trimmed === currentTitle) {
      setRenameChatId(null);
      setRenameDraft("");
      return;
    }

    try {
      const response = await apiRequest(`/api/chats/${chatId}`, {
        method: "PATCH",
        body: JSON.stringify({ title: trimmed }),
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Unable to rename chat");
      }

      setChats((current) =>
        current.map((chat) => (chat.id === chatId ? { ...chat, title: data.title } : chat))
      );
      setRenameChatId(null);
      setRenameDraft("");
      setMenuOpenChatId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to rename chat");
    }
  }

  async function deleteFailedResponse(message: MessageItem) {
    if (busy) return;
    setDeletingResponse(true);
    setError("");
    try {
      const response = await apiRequest(`/api/chats/${message.chat_id}/messages/${message.id}`, { method: "DELETE" });
      if (!response.ok) throw await responseError(response, "Unable to delete response");
      if (selectedId.current === message.chat_id) {
        setMessages(current => current.filter(item => item.id !== message.id));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to delete response");
    } finally {
      setDeletingResponse(false);
    }
  }

  async function handleDeleteChat(chatId: number) {
    if (busy) return;
    try {
      const response = await apiRequest(`/api/chats/${chatId}`, {
        method: "DELETE",
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || "Unable to delete chat");
      }

      const remainingChats = chats.filter((chat) => chat.id !== chatId);
      setChats(remainingChats);
      setMenuOpenChatId(null);

      if (selectedChatId === chatId) {
        if (remainingChats.length > 0) {
          const nextChatId = remainingChats[0].id;
          selectedId.current = nextChatId;
          setSelectedChatId(nextChatId);
          await loadMessages(nextChatId);
          await loadTasks(nextChatId);
        } else {
          setSelectedChatId(null);
          selectedId.current = null;
          setMessages([]);
          setTasks([]);
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to delete chat");
    }
  }

  function handleStopStreaming() {
    // The request's catch block persists Stop before enabling another Retry.
    abortController?.abort();
  }

  async function handleSendMessage(e: FormEvent) {
    e.preventDefault();
    if (draft.trim()) await runResponse();
  }

  async function runResponse(retry?: MessageItem, action: "retry" | "regenerate" | "edit" = "retry", edited?: { id: number; content: string }) {
    if (!selectedChatId || busy) return;
    const chatId = selectedChatId;
    const prompt = draft.trim();
    if (!retry && !prompt) return;
    const placeholderId = retry?.id ?? nextTemporaryId.current;
    if (!retry) nextTemporaryId.current -= 2;
    const userId = placeholderId - 1;
    let responseId = placeholderId;
    let text = "";
    let finished = false;
    const controller = new AbortController();
    setAbortController(controller);
    setIsStreaming(true);
    setError("");
    if (retry) {
      setMessages(current => current.map(m => m.id === retry.id ? { ...m, content: "", status: "generating" } : m));
    } else {
      setDraft("");
      const created_at = new Date().toISOString();
      setMessages(current => [...current,
        { id: userId, chat_id: chatId, role: "user", content: prompt, status: "completed", created_at },
        { id: placeholderId, chat_id: chatId, role: "assistant", content: "", status: "generating", created_at },
      ]);
    }
    try {
      const endpoint = retry ? `/api/chats/${chatId}/messages/${edited?.id ?? retry.id}/${action}` : `/api/chats/${chatId}/messages/stream`;
      const response = await apiRequest(endpoint, {
        method: "POST",
        body: edited ? JSON.stringify({ content: edited.content }) : retry ? undefined : JSON.stringify({ content: prompt, attachment_ids: attachment ? [attachment.id] : [] }), signal: controller.signal,
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(errorDetail(data, "Unable to send message"));
      }
      const reader = response.body?.getReader();
      if (!reader) throw new Error("Streaming response is unavailable.");
      const decoder = new TextDecoder();
      let buffer = "";
      while (!finished) {
        const result = await reader.read();
        if (result.done) {
          if (!finished) throw new Error("The connection ended before the reply completed.");
          break;
        }
        buffer += decoder.decode(result.value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop() ?? "";
        for (const frame of events) {
          const payload = frame.split("\n").filter(line => line.startsWith("data:"))
            .map(line => line.slice(5).trimStart()).join("\n");
          if (!payload) continue;
          const parsed = JSON.parse(payload);
          if (parsed.type === "started") {
            if (!retry) setAttachment(null);
            responseId = parsed.message.id;
            setMessages(current => current.map(m => {
              if (m.id === placeholderId) return { ...parsed.message, content: "", status: "generating" };
              if (m.id === userId && parsed.user_message) return parsed.user_message;
              return m;
            }));
          } else if (parsed.type === "chunk") {
            text += parsed.content ?? "";
            const content = text;
            const id = responseId;
            setMessages(current => current.map(m => m.id === id ? { ...m, content, status: "generating" } : m));
          } else if (parsed.type === "done" || parsed.type === "error") {
            finished = true;
            const id = responseId;
            setMessages(current => current.map(m => m.id === id ? parsed.message : m));
            if (parsed.type === "error") setError(parsed.detail || "Couldn't generate a response.");
            break;
          }
        }
      }
      if (!retry) {
        const currentChat = chats.find(chat => chat.id === chatId);
        if (currentChat && isGenericChatTitle(currentChat.title)) {
          const renamed = await apiRequest(`/api/chats/${chatId}`, { method: "PATCH", body: JSON.stringify({ title: generateChatTitle(prompt) }) });
          if (renamed.ok) {
            const next = await renamed.json();
            setChats(current => current.map(chat => chat.id === chatId ? next : chat));
          }
        }
      }
    } catch (err) {
      const stopped = err instanceof DOMException && err.name === "AbortError";
      if (!stopped) setError(err instanceof Error ? err.message : "Unable to generate a response");
      const id = responseId;
      const partialText = text || retry?.content || "";
      setMessages(current => current.map(m => m.id === id
        ? { ...m, content: partialText, status: "interrupted" } : m));
      if (responseId > 0 && !finished) {
        await apiRequest(`/api/chats/${chatId}/messages/${responseId}/stop`, { method: "POST" }).catch(() => undefined);
      }
    } finally {
      await loadMessages(chatId).catch(() => undefined);
      setIsStreaming(false);
      setAbortController(null);
    }
  }

  useEffect(() => {
    if (!localStorage.getItem("access_token")) {
      router.replace("/login");
      return;
    }
    let cancelled = false;
    void apiRequest(`/api/chats?q=${encodeURIComponent(query)}&archived=${archivedView}`).then(async response => {
      if (!response.ok) throw await responseError(response, "Unable to load chats");
      const data: ChatItem[] = await response.json();
      if (cancelled) return;
      setChats(data);
      if (data.length > 0) {
        const chatId = data.find(c => c.id === selectedId.current)?.id ?? data[0].id;
        const [history, taskList] = await Promise.all([
          apiRequest(`/api/chats/${chatId}/messages`), apiRequest(`/api/chats/${chatId}/tasks`),
        ]);
        if (!history.ok) throw await responseError(history, "Unable to load messages");
        if (!taskList.ok) throw await responseError(taskList, "Unable to load tasks");
        const rows = await history.json();
        const taskRows = taskList.ok ? await taskList.json() : [];
        if (cancelled) return;
        selectedId.current = chatId;
        setSelectedChatId(chatId);
        setMessages(rows);
        setTasks(taskRows);
      } else { selectedId.current = null; setSelectedChatId(null); setMessages([]); setTasks([]); }
    }).catch((err) => {
      if (!cancelled && !(err instanceof SessionExpiredError)) {
        setError(err instanceof Error ? err.message : "Unable to load chats");
      }
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [router, query, archivedView]);

  const selectedChat = chats.find((chat) => chat.id === selectedChatId) ?? null;

  if (loading) {
    return (
      <main className="min-h-screen bg-zinc-950 text-white flex items-center justify-center">
        <div role="status">Loading your workspace...</div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-zinc-950 text-white flex flex-col lg:flex-row lg:h-dvh lg:overflow-hidden">
      <aside className="w-full lg:w-64 xl:w-72 shrink-0 border-b lg:border-r border-zinc-800 bg-zinc-900 p-4 lg:overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-xl font-semibold">AI Multitask</h1>
          <button
            onClick={() => {
              localStorage.removeItem("access_token");
              router.replace("/login");
            }}
            className="text-sm text-zinc-300 hover:text-white"
          >
            Logout
          </button>
        </div>

        <form onSubmit={handleCreateChat} className="mb-5 space-y-3">
          <input
            value={newChatTitle}
            onChange={(e) => setNewChatTitle(e.target.value)}
            className="w-full rounded-lg border border-zinc-700 bg-zinc-950 p-2.5"
            placeholder="New chat title"
          />
          <button type="submit" disabled={busy} className="w-full rounded-lg bg-white px-3 py-2 text-black font-medium">
            New chat
          </button>
        </form>

        <form className="mb-3 flex gap-2" onSubmit={e => { e.preventDefault(); setQuery(searchDraft.trim()); }}>
          <input aria-label="Search conversations" placeholder="Search conversations" value={searchDraft} maxLength={200}
            disabled={busy} onChange={e => setSearchDraft(e.target.value)} className="min-w-0 flex-1 rounded border border-zinc-700 bg-zinc-950 p-2 text-sm" />
          <button disabled={busy} className="text-sm underline">Search</button>
        </form>
        <label className="mb-3 flex gap-2 text-sm"><input type="checkbox" checked={archivedView} disabled={busy}
          onChange={e => setArchivedView(e.target.checked)} />Archived conversations</label>
        <div className="space-y-2 max-h-64 lg:max-h-none overflow-y-auto">
          {chats.map((chat) => (
            <div key={chat.id} className="relative">
              <button
                type="button"
                disabled={busy}
                onClick={async () => {
                  selectedId.current = chat.id;
                  setSelectedChatId(chat.id);
                  setAttachment(null);
                  try {
                    await loadMessages(chat.id);
                    await loadTasks(chat.id);
                  } catch {
                    setError("Unable to load chat history");
                  }
                }}
                className={`w-full rounded-xl border p-3 pr-10 text-left ${
                  selectedChatId === chat.id
                    ? "border-white bg-zinc-800"
                    : "border-zinc-700 bg-zinc-950"
                }`}
              >
                <div className="font-medium truncate">{chat.is_pinned ? "Pinned: " : ""}{chat.title}</div>
                <div className="text-xs text-zinc-400 mt-1">Chat #{chat.id}</div>
              </button>

              <div className="absolute right-2 top-3">
                <button
                  type="button"
                  aria-label={`More actions for ${chat.title}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    setMenuOpenChatId((current) => (current === chat.id ? null : chat.id));
                  }}
                  className="rounded-md border border-zinc-700 bg-zinc-950 px-2 py-1 text-lg leading-none text-zinc-200"
                >
                  ⋯
                </button>

                {menuOpenChatId === chat.id && (
                  <div className="absolute right-0 z-20 mt-2 w-32 rounded-lg border border-zinc-700 bg-zinc-950 p-1 shadow-lg">
                    <button
                      type="button"
                      onClick={() => {
                        setRenameChatId(chat.id);
                        setRenameDraft(chat.title);
                        setMenuOpenChatId(null);
                      }}
                      className="w-full rounded px-2 py-1.5 text-left text-sm hover:bg-zinc-800"
                    >
                      Rename
                    </button>
                    <button type="button" disabled={busy} onClick={() => updateChatFlags(chat, { is_pinned: !chat.is_pinned })}
                      className="w-full rounded px-2 py-1.5 text-left text-sm hover:bg-zinc-800">{chat.is_pinned ? "Unpin" : "Pin"}</button>
                    <button type="button" disabled={busy} onClick={() => updateChatFlags(chat, { is_archived: !chat.is_archived })}
                      className="w-full rounded px-2 py-1.5 text-left text-sm hover:bg-zinc-800">{chat.is_archived ? "Unarchive" : "Archive"}</button>
                    <button
                      type="button"
                      onClick={() => handleDeleteChat(chat.id)}
                      className="w-full rounded px-2 py-1.5 text-left text-sm text-red-300 hover:bg-zinc-800"
                    >
                      Delete
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>

        {renameChatId !== null && (
          <div className="mt-4 rounded-xl border border-zinc-700 bg-zinc-950 p-3">
            <label className="mb-2 block text-xs uppercase tracking-wide text-zinc-400">
              Rename chat
            </label>
            <input
              value={renameDraft}
              onChange={(e) => setRenameDraft(e.target.value)}
              className="w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm"
            />
            <div className="mt-3 flex gap-2">
              <button
                type="button"
                onClick={() => handleRenameChat(renameChatId, chats.find((chat) => chat.id === renameChatId)?.title ?? "")}
                className="rounded-lg bg-white px-3 py-2 text-sm font-medium text-black"
              >
                Save
              </button>
              <button
                type="button"
                onClick={() => {
                  setRenameChatId(null);
                  setRenameDraft("");
                }}
                className="rounded-lg border border-zinc-700 px-3 py-2 text-sm text-zinc-200"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </aside>

      <section className="flex-1 min-w-0 min-h-[60dvh] flex flex-col">
        <header className="border-b border-zinc-800 p-4">
          <h2 className="break-words text-lg font-medium">
            {selectedChat ? selectedChat.title : "Select a chat"}
          </h2>
        </header>

        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {error && (
            <div className="rounded-lg border border-red-700 bg-red-950/50 px-3 py-2 text-red-200">
              {error}
            </div>
          )}

          {loading ? <div role="status">Loading chat history...</div> : messages.length === 0 ? (
            <div className="text-zinc-400">No messages yet. Start the conversation.</div>
          ) : (
            messages.map((message) => (
              <div
                key={message.id}
                className={`min-w-0 max-w-2xl rounded-2xl px-4 py-3 ${
                  message.role === "user"
                    ? "ml-auto bg-white text-black"
                    : "bg-zinc-800 text-zinc-100"
                }`}
              >
                <div className="text-xs uppercase tracking-wide opacity-70 mb-1">
                  {message.role}
                </div>
                {message.content && message.status !== "failed" ? (
                  message.role === "assistant" ? <Markdown>{message.content}</Markdown> :
                    <div className="whitespace-pre-wrap break-words">{message.content.split("\n\nAttached document:")[0]}
                      {message.content.includes("\n\nAttached document:") && <details className="mt-2 text-sm"><summary>Attached document</summary>{message.content.split("\n\nAttached document:").slice(1).join("\n")}</details>}
                    </div>
                ) : <div role="status" className={message.status === "generating" ? "animate-pulse" : ""}>
                  {message.status === "failed" ? "Generation failed" : message.status === "generating" ? "\u25cf \u25cf \u25cf Thinking..." : "Response interrupted."}
                </div>}
                {message.role === "assistant" && message.task_run_id && message.status !== "generating" && <div className="mt-2 text-xs text-zinc-400">Task plan #{message.task_run_id}. Retry tasks in Task Activity to update this answer.</div>}
                {message.role === "assistant" && message.content && ["completed", "interrupted"].includes(message.status) &&
                  <button type="button" className="mt-2 text-xs underline" onClick={() => copyAnswer(message)}>
                    {copiedMessageId === message.id ? "Copied" : "Copy"}
                  </button>}
                {!message.task_run_id && message.status !== "generating" && message.id > 0 && <div className="mt-2 flex gap-3 text-xs">
                  {((message.role === "assistant" && message.status !== "failed") || message.id === messages.filter(m => m.role === "user").at(-1)?.id) &&
                    <button disabled={busy} className="underline" onClick={() => { setEditingMessage(message); setEditText(message.content); }}>{message.role === "user" ? "Edit prompt" : "Edit answer"}</button>}
                  {message.role === "assistant" && message.status === "completed" && message.id === messages.at(-1)?.id &&
                    <button disabled={busy} className="underline" onClick={() => runResponse(message, "regenerate")}>Regenerate</button>}
                </div>}
                {message.status === "interrupted" && message.content && <div className="mt-2 text-sm text-amber-300">Response interrupted.</div>}
                {message.status === "generating" && !isStreaming && <button type="button" className="mt-2 text-sm underline" onClick={async () => {
                  const response = await apiRequest(`/api/chats/${message.chat_id}/messages/${message.id}/stop`, { method: "POST" });
                  if (response.ok) await loadMessages(message.chat_id);
                }}>Stop unfinished response</button>}
                {message.role === "assistant" && !message.task_run_id && ["failed", "interrupted", "incomplete", "stopped"].includes(message.status) && message.id > 0 && (
                  <button type="button" disabled={busy} onClick={() => runResponse(message)}
                    className="mt-3 rounded-lg border border-zinc-500 px-3 py-1.5 text-sm disabled:opacity-50">Retry</button>
                )}
                {message.role === "assistant" && !message.task_run_id && message.status === "failed" && message.id > 0 &&
                  <button type="button" disabled={busy} onClick={() => deleteFailedResponse(message)}
                    className="ml-2 mt-3 rounded-lg border border-red-500 px-3 py-1.5 text-sm disabled:opacity-50">Delete</button>}
              </div>
            ))
          )}
        </div>

        {editingMessage && <div className="border-t border-zinc-700 p-4">
          <label htmlFor="edit-message">{editingMessage.role === "user" ? "Edit question and regenerate" : "Edit answer"}</label>
          <textarea id="edit-message" value={editText} onChange={e => setEditText(e.target.value)} rows={5} maxLength={60000}
            className="mt-2 w-full rounded-lg bg-zinc-900 p-3" />
          <button type="button" disabled={busy || !editText.trim()} onClick={saveMessageEdit} className="mr-4 underline">Save</button>
          <button type="button" onClick={() => setEditingMessage(null)} className="underline">Cancel</button>
        </div>}
        <form onSubmit={handleSendMessage} className="border-t border-zinc-800 p-4">
          <div className="mb-3 text-sm">
            <label>Attach PDF, CSV, TXT or Markdown (5 MB)
              <input type="file" accept=".pdf,.csv,.txt,.md" disabled={!selectedChat || busy} className="ml-2 max-w-full"
                onChange={e => { const file = e.target.files?.[0]; if (file) void uploadFile(file); e.target.value = ""; }} />
            </label>
            {uploading && <span role="status"> Reading file...</span>}
            {attachment && <div className="mt-2 text-emerald-300">{attachment.filename} ready for the next message or task plan.
              <button type="button" disabled={busy} className="ml-3 underline" onClick={() => setAttachment(null)}>Remove</button></div>}
          </div>
          <div className="flex gap-3">
            <textarea
              rows={2}
              aria-label="Message"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder={selectedChat ? "Type a message..." : "Create a chat to begin"}
              disabled={!selectedChat || busy}
              className="flex-1 rounded-xl border border-zinc-700 bg-zinc-900 px-4 py-3 disabled:opacity-50"
            />
            <button
              type={isStreaming ? "button" : "submit"}
              onClick={isStreaming ? handleStopStreaming : undefined}
              disabled={!selectedChat || taskBusy || uploading || (!draft.trim() && !isStreaming)}
              className="rounded-xl bg-white px-5 py-3 font-medium text-black disabled:opacity-50"
            >
              {isStreaming ? "■ Stop" : "Send"}
            </button>
          </div>
        </form>
      </section>

      <aside className="w-full lg:w-72 xl:w-80 shrink-0 border-t lg:border-l border-zinc-800 bg-zinc-900 p-4 overflow-y-auto">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold">Task Activity</h3>
          <button
            type="button"
            onClick={() => selectedChatId && loadTasks(selectedChatId).catch(() => setError("Unable to load tasks"))}
            className="rounded-md border border-zinc-700 px-2 py-1 text-xs text-zinc-200"
          >
            Refresh
          </button>
        </div>

        <div className="mb-4 space-y-2">
          <label htmlFor="task-plan" className="text-sm">What should the tasks achieve?</label>
          <textarea id="task-plan" value={taskPrompt} onChange={e => setTaskPrompt(e.target.value)} disabled={busy}
            placeholder="Compare Java and Python, and draft a study plan" className="w-full rounded-lg border border-zinc-700 bg-zinc-950 p-3 text-sm" />
          <button type="button" disabled={!selectedChat || busy || !taskPrompt.trim()} onClick={() => handleTaskAction("plan")}
            className="w-full rounded-lg bg-white p-2 text-sm text-black disabled:opacity-50">Plan tasks</button>
          <button type="button" disabled={!selectedChat || busy || !tasks.some(t => ["pending", "failed", "cancelled"].includes(t.status)) || tasks.some(t => t.status === "in_progress")}
            onClick={() => handleTaskAction("run")} className="w-full rounded-lg border border-emerald-500 p-2 text-sm disabled:opacity-50">
            {taskBusy ? "Working..." : "Run pending / retry failed tasks"}</button>
          {hasRunningTasks && <button type="button" onClick={cancelTasks} className="w-full rounded border border-red-500 p-2 text-sm">Stop tasks</button>}
          <p role="status" className="text-sm text-emerald-300">All tasks in this chat: {tasks.filter(t => t.status === "completed").length} / {tasks.length} complete</p>
          <p className="text-xs text-zinc-400">Up to 8 tasks per plan, 3 at a time. One combined answer is saved to the chat. Runs time out after 3 minutes.</p>
          <input
            value={newTaskTitle}
            onChange={(e) => setNewTaskTitle(e.target.value)}
            placeholder="Add a task"
            className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm"
          />
          <button
            type="button"
            onClick={handleCreateTask}
            disabled={!selectedChat || busy || !newTaskTitle.trim()}
            className="w-full rounded-lg bg-white px-3 py-2 text-sm font-medium text-black disabled:opacity-50"
          >
            Add task
          </button>
        </div>

        {[...new Set(tasks.map(t => t.run_id).filter((id): id is number => id !== null))].map(runId => {
          const planTasks = tasks.filter(t => t.run_id === runId);
          return <div key={runId} className="mb-3 rounded-lg border border-zinc-700 p-3 text-sm">
            <div>Plan #{runId}: {planTasks.filter(t => t.status === "completed").length} / {planTasks.length} complete</div>
            {planTasks.some(t => ["pending", "failed", "cancelled"].includes(t.status)) &&
              <button type="button" disabled={busy} className="mt-2 underline" onClick={() => handleTaskAction("run", undefined, runId)}>Run / retry this plan</button>}
          </div>;
        })}
        {tasks.some(t => t.result) && <details className="mb-4 rounded-lg border border-zinc-700 p-3">
          <summary className="cursor-pointer text-sm">Combined results ({tasks.filter(t => t.status === "completed").length}/{tasks.length} completed)</summary>
          <div className="mt-3 space-y-4">{tasks.map(t => <section key={t.id}><h4 className="font-medium">{t.title}</h4>
            <Markdown>{t.result || t.error || `Task ${t.status}`}</Markdown></section>)}</div>
        </details>}
        <div className="space-y-3">
          {tasks.length === 0 ? (
            <div className="rounded-lg border border-dashed border-zinc-700 p-3 text-sm text-zinc-400">
              No tasks for this chat yet.
            </div>
          ) : (
            tasks.map((task) => (
              <div key={task.id} className="rounded-xl border border-zinc-700 bg-zinc-950 p-3">
                <div className="mb-2 flex items-start justify-between gap-2">
                  <div>
                    <div className="font-medium text-sm">{task.title}</div>
                    {task.description && (
                      <div className="mt-1 text-xs text-zinc-400">{task.description}</div>
                    )}
                  </div>
                  <span className="rounded-full border border-zinc-600 px-2 py-0.5 text-[10px] uppercase tracking-wide text-zinc-200">
                    {taskStatusLabel(task.status)}
                  </span>
                </div>

                <div className="mb-2 h-2 overflow-hidden rounded-full bg-zinc-800">
                  <div
                    className="h-full rounded-full bg-emerald-400"
                    style={{ width: `${task.progress}%` }}
                  />
                </div>

                {["failed", "cancelled"].includes(task.status) && <button type="button" disabled={busy}
                  onClick={() => handleTaskAction("run", task.id)} className="mb-2 rounded border border-zinc-500 px-3 py-1 text-sm">Retry</button>}
                {task.error && <p className="text-sm text-red-300">{task.error}</p>}
                {task.result && <details className="mt-2 text-sm"><summary className="cursor-pointer">View result</summary><Markdown>{task.result}</Markdown></details>}
              </div>
            ))
          )}
        </div>
      </aside>
    </main>
  );
}
