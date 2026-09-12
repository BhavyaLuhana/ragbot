export default function Citations({ citations }) {
  if (!citations || citations.length === 0) return null

  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {citations.map((c) => (
        <div
          key={c.chunk_id}
          title={c.snippet}
          className="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs text-slate-700 transition-colors hover:border-brand-500 hover:bg-brand-50"
        >
          <span className="font-medium">p.{c.page}</span>
          {c.section && (
            <>
              <span className="text-slate-400">·</span>
              <span className="max-w-[200px] truncate">{c.section}</span>
            </>
          )}
        </div>
      ))}
    </div>
  )
}