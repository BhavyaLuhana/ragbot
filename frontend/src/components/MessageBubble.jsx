import Citations from './Citations.jsx'

export default function MessageBubble({ message }) {
  const isUser = message.role === 'user'

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[75%] rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-sm ${
          isUser
            ? 'bg-brand-600 text-white'
            : message.error
              ? 'border border-red-200 bg-red-50 text-red-800'
              : 'border border-slate-200 bg-white text-slate-800'
        }`}
      >
        <div className="whitespace-pre-wrap break-words">
          {message.content}
          {message.streaming && (
            <span className="ml-0.5 inline-block h-4 w-2 animate-pulse bg-current align-middle" />
          )}
        </div>

        {!isUser && message.citations?.length > 0 && (
          <Citations citations={message.citations} />
        )}
      </div>
    </div>
  )
}