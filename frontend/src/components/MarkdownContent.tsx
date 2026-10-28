import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

interface MarkdownContentProps {
  children: string;
  className?: string;
}

export default function MarkdownContent({ children, className }: MarkdownContentProps) {
  return (
    <div className={cn("markdown-content", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  );
}
