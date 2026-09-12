import { useEffect, useRef } from 'react'
import MessageBubble from './MessageBubble.jsx'
import TypingIndicator from './TypingIndicator.jsx'

export default function ChatWindow({ messages, isStreaming }) {
  const endRef = useRef(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isStreaming])

  if (messages.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center px-6 text-center">
        <div className="max-w-md space-y-2">
          <div className="text-2xl">📘</div>
          <h2 className="text-lg font-semibold text-slate-800">
            Ask the handbook
          </h2>
          <p className="text-sm text-slate-500">
            Try &ldquo;What is the deployment policy?&rdquo; or &ldquo;How do
            I request production access?&rdquo;. Answers include page citations.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6">
      <div className="mx-auto flex max-w-3xl flex-col gap-4">
        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}
        {isStreaming && <TypingIndicator />}
        <div ref={endRef} />
      </div>
    </div>
  )
}