import { memo, useEffect, useState } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import rehypeHighlight from 'rehype-highlight'
import { createContext, useContext } from 'react'
import { raw } from '@/api/client'

/** Maps an attachment URL to the endpoint the current portal may call (students use /api/student/files/...). */
export const FileUrlContext = createContext<(src: string) => string>((s) => s)
export const useFileUrl = () => useContext(FileUrlContext)

/** Images served by the API need the bearer token, so they are fetched and shown from a blob URL. */
function AuthImage({ src, alt }: { src: string; alt?: string }) {
  const [url, setUrl] = useState<string>()
  const [failed, setFailed] = useState(false)
  const mapUrl = useFileUrl()
  useEffect(() => {
    let revoked = false
    let created: string | undefined
    raw(mapUrl(src).replace(/^\/api/, ''))
      .then((r) => (r.ok ? r.blob() : Promise.reject()))
      .then((b) => {
        if (revoked) return
        created = URL.createObjectURL(b)
        setUrl(created)
      })
      .catch(() => setFailed(true))
    return () => {
      revoked = true
      if (created) URL.revokeObjectURL(created)
    }
  }, [src, mapUrl])
  if (failed) return <span className="text-xs text-bad">[image unavailable]</span>
  if (!url) return <span className="inline-block h-16 w-24 animate-pulse rounded bg-raised" />
  return <img src={url} alt={alt ?? ''} loading="lazy" />
}

const D = { dir: 'auto' as const }
const components: Components = {
  p: ({ children }) => <p {...D}>{children}</p>,
  ul: ({ children }) => <ul {...D}>{children}</ul>,
  ol: ({ children }) => <ol {...D}>{children}</ol>,
  li: ({ children }) => <li {...D}>{children}</li>,
  h1: ({ children }) => <h1 {...D}>{children}</h1>,
  h2: ({ children }) => <h2 {...D}>{children}</h2>,
  h3: ({ children }) => <h3 {...D}>{children}</h3>,
  h4: ({ children }) => <h4 {...D}>{children}</h4>,
  blockquote: ({ children }) => <blockquote {...D}>{children}</blockquote>,
  th: ({ children }) => <th {...D}>{children}</th>,
  td: ({ children }) => <td {...D}>{children}</td>,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer nofollow">
      {children}
    </a>
  ),
  img: ({ src, alt }) => {
    if (!src) return null
    if (src.startsWith('/api/attachments/')) return <AuthImage src={src} alt={alt} />
    // Only attachments and https images; blocks tracking pixels from data:/http: sources.
    if (/^https:\/\//i.test(src)) return <img src={src} alt={alt ?? ''} loading="lazy" referrerPolicy="no-referrer" />
    return <span className="text-xs text-faint">[image: {alt || 'blocked source'}]</span>
  },
  table: ({ children }) => (
    <div className="overflow-x-auto">
      <table>{children}</table>
    </div>
  ),
}

function MarkdownImpl({ children, className = '' }: { children: string; className?: string }) {
  return (
    <div className={`prose-recall ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, [remarkMath, { singleDollarTextMath: true }]]}
        rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: false }], [rehypeHighlight, { detect: false, ignoreMissing: true }]]}
        components={components}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}
export const Markdown = memo(MarkdownImpl)
