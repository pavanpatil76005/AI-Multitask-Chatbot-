import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export default function Markdown({ children }: { children: string }) {
  return <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml
    components={{
      a: ({ children, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer">{children}</a>,
      // Do not load remote tracking images embedded in generated answers.
      img: ({ alt }) => <span className="text-zinc-400">[Image: {alt || "image"}]</span>,
      table: ({ children }) => <div className="overflow-x-auto"><table>{children}</table></div>,
    }}>{children}</ReactMarkdown></div>;
}
