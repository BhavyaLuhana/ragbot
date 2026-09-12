/**
 * Shape of the SSE event payloads emitted by the chat service.
 * Mirrors the Pydantic models in shared/shared/schemas/chat.py.
 *
 * @typedef {'user'|'assistant'} Role
 *
 * @typedef {Object} Citation
 * @property {string} chunk_id
 * @property {string} source
 * @property {number} page
 * @property {string} section
 * @property {number} score
 * @property {string} snippet
 *
 * @typedef {Object} ChatMessage
 * @property {string} id
 * @property {Role} role
 * @property {string} content
 * @property {Citation[]} citations
 * @property {boolean} [streaming]
 * @property {boolean} [error]
 *
 * @typedef {Object} StreamHandlers
 * @property {(sessionId: string) => void} onSession
 * @property {(text: string) => void} onToken
 * @property {(citations: Citation[]) => void} onCitations
 * @property {(message: string, retryable: boolean) => void} onError
 * @property {() => void} onDone
 */

export {}