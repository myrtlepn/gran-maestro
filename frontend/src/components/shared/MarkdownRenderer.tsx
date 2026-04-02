import { isValidElement, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import '@/styles/hljs-themes.css';
import { cn } from '@/lib/utils';

function MarkdownImage({ src, alt }: { src?: string; alt?: string }) {
  const [loadFailed, setLoadFailed] = useState(false);

  if (!src || loadFailed) {
    return <span className="text-xs text-muted-foreground italic">{alt?.trim() || '이미지를 불러올 수 없습니다.'}</span>;
  }

  return (
    <img
      src={src}
      alt={alt ?? ''}
      className="max-w-full h-auto rounded-md my-2"
      loading="lazy"
      onError={() => setLoadFailed(true)}
    />
  );
}

export function MarkdownRenderer({ content, className }: { content: string; className?: string }) {
  return (
    <div className={cn(className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          h1: ({ children }) => <h1 className="text-2xl font-bold text-foreground mt-6 mb-3 border-b border-border pb-2">{children}</h1>,
          h2: ({ children }) => <h2 className="text-xl font-bold text-foreground mt-5 mb-2">{children}</h2>,
          h3: ({ children }) => <h3 className="text-lg font-semibold text-foreground mt-4 mb-2">{children}</h3>,
          h4: ({ children }) => <h4 className="text-base font-semibold text-foreground mt-3 mb-1">{children}</h4>,
          h5: ({ children }) => <h5 className="text-sm font-semibold text-foreground mt-3 mb-1">{children}</h5>,
          h6: ({ children }) => <h6 className="text-xs font-semibold text-muted-foreground mt-2 mb-1">{children}</h6>,
          p: ({ children }) => <p className="text-sm text-foreground leading-7 mb-3">{children}</p>,
          a: ({ href, children }) => (
            <a
              href={href}
              className="text-primary underline underline-offset-4 hover:text-primary/80"
              target="_blank"
              rel="noopener noreferrer"
            >
              {children}
            </a>
          ),
          ul: ({ children }) => <ul className="list-disc pl-6 text-sm text-foreground mb-3 space-y-1">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal pl-6 text-sm text-foreground mb-3 space-y-1">{children}</ol>,
          li: ({ children }) => <li className="text-sm text-foreground leading-7 [&>p]:mb-0">{children}</li>,
          img: ({ src, alt }) => <MarkdownImage src={src} alt={alt} />,
          table: ({ children }) => (
            <div className="overflow-x-auto mb-4">
              <table className="w-full text-sm border-collapse border border-border">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-muted/50">{children}</thead>,
          tbody: ({ children }) => <tbody>{children}</tbody>,
          tr: ({ children }) => <tr className="border-b border-border">{children}</tr>,
          th: ({ children }) => <th className="text-left text-xs font-semibold text-muted-foreground px-3 py-2 border-r border-border last:border-r-0">{children}</th>,
          td: ({ children }) => <td className="text-sm text-foreground px-3 py-2 border-r border-border last:border-r-0">{children}</td>,
          blockquote: ({ children }) => (
            <blockquote className="border-l-4 border-border pl-4 my-3 text-sm text-muted-foreground italic">
              {children}
            </blockquote>
          ),
          hr: () => <hr className="border-border my-4" />,
          code: ({ className, children, node, ...props }) => {
            const isBlock = node?.position?.start.line !== node?.position?.end.line
              || String(children).includes('\n');
            return isBlock ? (
              <code className={cn("text-xs", className)} {...props}>{children}</code>
            ) : (
              <code className="px-1.5 py-0.5 rounded bg-muted font-mono text-xs text-foreground" {...props}>{children}</code>
            );
          },
          pre: ({ children }) => {
            const firstChild = Array.isArray(children) ? children[0] : children;
            const className = isValidElement<{ className?: string }>(firstChild) ? firstChild.props.className : undefined;
            const isD2Block = typeof className === 'string' && /\blanguage-d2\b/i.test(className);

            return (
              <div className="my-3">
                {isD2Block && (
                  <div className="mb-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                    D2가 설치되어 있지 않아 텍스트로 표시합니다.
                  </div>
                )}
                <pre className="rounded-lg bg-[#f6f8fa] dark:bg-[#0d1117] p-4 overflow-x-auto text-xs">{children}</pre>
              </div>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
