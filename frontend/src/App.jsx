import { useCallback, useRef, useState } from 'react'
import ChatWindow from './components/ChatWindow.jsx'
import InputBox from './components/InputBox.jsx'
import { streamChat } from './lib/sse.js'

const CHAT_URL =
  (import.meta.env.VITE_CHAT_URL || 'http://localhost:8003') + '/chat'

let nextId = 1
const newId = () => `msg-${nextId++}`

export default function App() {
  const [messages, setMessages] = useState([])
  const [isStreaming, setIsStreaming] = useState(false)
  const sessionIdRef = useRef(null)
  const abortRef = useRef(null)

  const handleSend = useCallback(async (text) => {
    const userMsg = {
      id: newId(),
      role: 'user',
      content: text,
      citations: [],
    }
    const assistantId = newId()
    const assistantMsg = {
      id: assistantId,
      role: 'assistant',
      content: '',
      citations: [],
      streaming: true,
    }
    setMessages((prev) => [...prev, userMsg, assistantMsg])
    setIsStreaming(true)

    const controller = new AbortController()
    abortRef.current = controller

    await streamChat({
      url: CHAT_URL,
      body: {
        session_id: sessionIdRef.current,
        message: text,
      },
      signal: controller.signal,
      handlers: {
        onSession: (sid) => {
          sessionIdRef.current = sid
        },
        onToken: (token) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? { ...m, content: m.content + token }
                : m,
            ),
          )
        },
        onCitations: (citations) => {
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantId ? { ...m, citations } : m)),
          )
        },
        onError: (message, retryable) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    content: m.content || message,
                    error: true,
                    streaming: false,
                  }
                : m,
            ),
          )
        },
        onDone: () => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, streaming: false } : m,
            ),
          )
          setIsStreaming(false)
          abortRef.current = null
        },
      },
    })
  }, [])

  const handleReset = () => {
    abortRef.current?.abort()
    setMessages([])
    sessionIdRef.current = null
    setIsStreaming(false)
  }

  return (
    <div className="flex h-full flex-col bg-slate-50">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-xl">📘</span>
          <div>
            <div className="text-sm font-semibold text-slate-800">
              TechCorp Handbook Assistant
            </div>
            <div className="text-xs text-slate-500">
              Hybrid RAG · HyDE · RRF · Cross-encoder
            </div>
          </div>
        </div>
        <button
          onClick={handleReset}
          className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-600 transition-colors hover:border-slate-300 hover:bg-slate-50"
        >
          New chat
        </button>
      </header>

      <ChatWindow messages={messages} isStreaming={isStreaming} />
      <InputBox onSend={handleSend} disabled={isStreaming} />
    </div>
  )
}