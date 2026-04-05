import { useState, useRef, useEffect, useCallback } from 'react';
import { Send, Bot, User, Bell } from 'lucide-react';
import * as api from '../api';
import { useApp, type ChatMsg } from '../store';

export default function Chat() {
  const { addToast, chatMessages, addChatMessage, updateChatMessage } = useApp();
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [chatMessages, sending, scrollToBottom]);

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || sending) return;

    setInput('');
    addChatMessage('user', text);
    setSending(true);

    const startTime = performance.now();
    // Create a placeholder agent message that will be updated with streamed tokens
    const msgId = addChatMessage('agent', '');

    try {
      await api.streamChatMessage(
        text,
        // onToken — append each token to the message
        (token) => {
          updateChatMessage(msgId, (prev) => ({
            content: prev.content + token,
          }));
        },
        // onDone — set final content and response time
        (fullResponse) => {
          const elapsed = Math.round(performance.now() - startTime);
          updateChatMessage(msgId, () => ({
            content: fullResponse,
            responseTimeMs: elapsed,
          }));
        },
      );
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : 'Unknown error';
      // Remove the empty placeholder and add error message
      updateChatMessage(msgId, () => ({
        role: 'system' as const,
        content: `Error: ${errMsg}`,
      }));
      addToast(`Chat error: ${errMsg}`, 'error');
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <div className="chat-page">
      <div className="chat-container">
        {/* Messages area */}
        <div className="chat-messages">
          {chatMessages.map((m) => (
            <MessageBubble key={m.id} msg={m} />
          ))}
          {sending && chatMessages[chatMessages.length - 1]?.content === '' && (
            <div className="chat-row agent">
              <div className="chat-avatar agent-avatar"><Bot size={18} /></div>
              <div className="chat-content">
                <div className="chat-bubble agent-bubble">
                  <div className="typing-indicator">
                    <span /><span /><span />
                  </div>
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input area */}
        <div className="chat-input-area">
          <form className="chat-form" onSubmit={handleSubmit}>
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Message AutoOps AI…"
              autoComplete="off"
              disabled={sending}
              className="chat-input"
            />
            <button
              type="submit"
              className="chat-send-btn"
              disabled={sending || !input.trim()}
              title="Send message"
            >
              <Send size={18} />
            </button>
          </form>
          <div className="chat-disclaimer">
            AutoOps AI can make mistakes. Verify critical actions before executing.
          </div>
        </div>
      </div>
    </div>
  );
}

function MessageBubble({ msg }: { msg: ChatMsg }) {
  const timeStr = msg.timestamp.toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
  const dateStr = msg.timestamp.toLocaleDateString([], {
    month: 'short',
    day: 'numeric',
  });

  if (msg.role === 'system') {
    return (
      <div className="chat-row system">
        <div className="chat-system-msg">
          <Bell size={14} />
          <MarkdownContent content={msg.content} />
          <span className="chat-timestamp">{timeStr}</span>
        </div>
      </div>
    );
  }

  const isAgent = msg.role === 'agent';
  const isStreaming = isAgent && msg.content.length > 0 && msg.responseTimeMs == null;

  return (
    <div className={`chat-row ${msg.role}`}>
      <div className={`chat-avatar ${isAgent ? 'agent-avatar' : 'user-avatar'}`}>
        {isAgent ? <Bot size={18} /> : <User size={18} />}
      </div>
      <div className="chat-content">
        <div className="chat-meta">
          <span className="chat-sender">{isAgent ? 'AutoOps AI' : 'You'}</span>
          <span className="chat-timestamp">{dateStr} {timeStr}</span>
          {isAgent && msg.responseTimeMs != null && (
            <span className="chat-response-time">
              {msg.responseTimeMs >= 1000
                ? `${(msg.responseTimeMs / 1000).toFixed(1)}s`
                : `${msg.responseTimeMs}ms`}
            </span>
          )}
        </div>
        <div className={`chat-bubble ${isAgent ? 'agent-bubble' : 'user-bubble'}`}>
          {isAgent ? <MarkdownContent content={msg.content} /> : msg.content}
          {isStreaming && <span className="streaming-cursor" />}
        </div>
      </div>
    </div>
  );
}

/** Simple markdown renderer — handles headings, bold, italic, code blocks, inline code, lists, line breaks. */
function MarkdownContent({ content }: { content: string }) {
  const html = renderMarkdown(content);
  return <div className="markdown-body" dangerouslySetInnerHTML={{ __html: html }} />;
}

function renderMarkdown(text: string): string {
  // Sanitize HTML entities first
  let s = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // Code blocks (```...```)
  s = s.replace(/```(\w*)\n?([\s\S]*?)```/g, (_m, lang, code) => {
    return `<pre class="code-block"><code class="lang-${lang}">${code.trim()}</code></pre>`;
  });

  // Inline code (`...`)
  s = s.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');

  // Bold (**text** or __text__)
  s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/__(.+?)__/g, '<strong>$1</strong>');

  // Italic (*text* or _text_)
  s = s.replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, '<em>$1</em>');

  // Headings
  s = s.replace(/^### (.+)$/gm, '<h4>$1</h4>');
  s = s.replace(/^## (.+)$/gm, '<h3>$1</h3>');
  s = s.replace(/^# (.+)$/gm, '<h2>$1</h2>');

  // Unordered lists
  s = s.replace(/^[-*] (.+)$/gm, '<li>$1</li>');
  s = s.replace(/((?:<li>.*<\/li>\n?)+)/g, '<ul>$1</ul>');

  // Numbered lists
  s = s.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');

  // Line breaks (double newline = paragraph, single = <br>)
  s = s.replace(/\n{2,}/g, '</p><p>');
  s = s.replace(/\n/g, '<br>');

  // Wrap in paragraph
  if (!s.startsWith('<')) {
    s = '<p>' + s + '</p>';
  }

  return s;
}
