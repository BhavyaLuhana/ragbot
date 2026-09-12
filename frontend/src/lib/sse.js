/**
 * SSE client for the chat service.
 *
 * The browser's native EventSource only supports GET. Our POST /chat
 * endpoint streams via SSE-in-a-POST-response, which EventSource can't
 * consume. So we implement a small SSE parser over fetch + ReadableStream.
 */

/**
 * @param {Object} params
 * @param {string} params.url
 * @param {Object} params.body
 * @param {import('../types/chat.js').StreamHandlers} params.handlers
 * @param {AbortSignal} [params.signal]
 */
export async function streamChat({ url, body, handlers, signal }) {
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify(body),
    signal,
  })

  if (!response.ok) {
    const text = await response.text().catch(() => '')
    handlers.onError(
      `Server returned HTTP ${response.status}: ${text.slice(0, 200)}`,
      response.status >= 500,
    )
    handlers.onDone()
    return
  }

  if (!response.body) {
    handlers.onError('Response has no body — SSE not supported?', false)
    handlers.onDone()
    return
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      // SSE messages are separated by a blank line (\n\n).
      let idx
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const rawEvent = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        handleEvent(rawEvent, handlers)
      }
    }

    if (buffer.trim()) {
      handleEvent(buffer, handlers)
    }
  } catch (err) {
    if (err.name === 'AbortError') return
    handlers.onError(err.message || 'Streaming error', true)
  } finally {
    handlers.onDone()
  }
}

/**
 * @param {string} block
 * @param {import('../types/chat.js').StreamHandlers} handlers
 */
function handleEvent(block, handlers) {
  let eventType = null
  const dataLines = []

  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) {
      eventType = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim())
    }
  }

  if (!eventType) return
  const payload = dataLines.join('\n')
  let obj = null
  try {
    obj = payload ? JSON.parse(payload) : {}
  } catch {
    return
  }

  switch (eventType) {
    case 'session':
      handlers.onSession(obj.session_id)
      break
    case 'token':
      handlers.onToken(obj.text ?? '')
      break
    case 'citations':
      handlers.onCitations(obj.citations ?? [])
      break
    case 'error':
      handlers.onError(obj.message ?? 'Unknown error', Boolean(obj.retryable))
      break
    case 'done':
      break
    default:
      break
  }
}