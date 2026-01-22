import React, { useState, useEffect, useRef } from 'react';
import {
  Send,
  Bot,
  User,
  Loader2,
  RefreshCw,
  AlertCircle
} from 'lucide-react';

// ✅ FastAPI endpoint
const BACKEND_CHAT_URL = "/chat"; 
// kalau tidak pakai proxy Vite, ganti:
// const BACKEND_CHAT_URL = "http://127.0.0.1:8000/chat";

export default function App() {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content:
        "Halo! Saya Asisten Satu Data Banyuwangi. Ada yang bisa saya bantu terkait data pembangunan hari ini?",
      type: 'text'
    }
  ]);

  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [error, setError] = useState(null);
  const messagesEndRef = useRef(null);

  // ✅ Knowledge base diambil dari /dataset_catalog.json
  const [knowledgeBase, setKnowledgeBase] = useState([]);
  const [kbLoaded, setKbLoaded] = useState(false);

  useEffect(() => {
    fetch("/dataset_catalog.json")
      .then(r => r.json())
      .then(data => {
        const items = Array.isArray(data) ? data : (data.datasets || []);
        const titles = items
          .map(x => (x.title || x.judul || "").trim())
          .filter(Boolean);
        setKnowledgeBase(titles);
        setKbLoaded(true);
      })
      .catch(() => {
        setKnowledgeBase([]);
        setKbLoaded(true);
      });
  }, []);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isTyping]);

  const findRelevantDatasets = (query) => {
    const q = (query || "").toLowerCase().trim();
    if (q.length < 3) return [];
    if (!knowledgeBase.length) return [];

    return knowledgeBase
      .filter(title => title.toLowerCase().includes(q))
      .slice(0, 3);
  };

  // ✅ Call FastAPI
  const callFastAPI = async (message) => {
    const sid = localStorage.getItem("session_id") || "demo";
    localStorage.setItem("session_id", sid);

    const response = await fetch(BACKEND_CHAT_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        session_id: sid,
        name: "string",
        phone: "string"
      }),
    });

    if (!response.ok) {
      const txt = await response.text();
      throw new Error(txt || "Backend error");
    }

    return await response.json();
  };
  const isGreeting = (t) => {
    const s = (t || "").toLowerCase().trim();
    return /^(halo|hai|hi|hei|hello|ass?alam(u'?alaikum)?|pagi|siang|sore|malam)\b/.test(s);
  };

  const isIdentityQuestion = (t) => {
    const s = (t || "").toLowerCase();
    return /(kamu siapa|siapa kamu|ini bot apa|asisten apa|apa fungsimu|apa yang bisa kamu lakukan)/.test(s);
  };

  const cannedReply = (t) => {
    if (isGreeting(t)) {
      return "Halo! Saya Asisten Satu Data Banyuwangi. Kamu mau cari dataset, info fitur portal, atau prosedur request data?";
    }
    if (isIdentityQuestion(t)) {
      return "Saya Asisten Satu Data Banyuwangi. Saya bisa membantu: (1) cari judul dataset, (2) jelaskan fitur portal, (3) jawab FAQ/prosedur, dan (4) ringkas isi dokumen jika ada lampiran PDF.";
    }
    return null;
  };

  const handleSendMessage = async (e) => {
    e.preventDefault();
    if (!input.trim() || isTyping) return;

    const userQuery = input.trim();
    setInput('');
    setError(null);
    setMessages(prev => [...prev, { role: 'user', content: userQuery }]);
    const quick = cannedReply(userQuery);
    if (quick) {
      setMessages(prev => [...prev, { role: 'assistant', content: quick }]);
      setIsTyping(false);
      return;
    }

    setIsTyping(true);

    // (tetap kamu simpan, walau backend belum pakai)
    const foundData = findRelevantDatasets(userQuery);
    const contextStr = foundData.length > 0
      ? `Data tersedia: ${foundData.join(", ")}`
      : "Tidak ada dataset spesifik ditemukan.";

    try {
      const res = await callFastAPI(userQuery);

      const cleanResponse = (res?.answer || "")
        .replace(/<\/?[^>]+(>|$)/g, "")
        .trim();

      setMessages(prev => [...prev, {
        role: 'assistant',
        content: cleanResponse || "Maaf, saya tidak mendapat jawaban."
      }]);
    } catch (err) {
      setError("Gagal menghubungi server FastAPI. Pastikan backend sedang berjalan.");
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: "Maaf, terjadi kendala teknis. Silakan coba lagi nanti.",
        type: 'error'
      }]);
    } finally {
      setIsTyping(false);
    }
  };

  const resetChat = () => {
    setMessages([{
      role: 'assistant',
      content: "Halo! Saya Asisten Satu Data Banyuwangi. Ada yang bisa saya bantu terkait data pembangunan hari ini?"
    }]);
    setError(null);
  };

  return (
    <div className="flex flex-col h-screen bg-slate-50 font-sans text-slate-900">
      {/* Header */}
      <header className="bg-white border-b border-slate-200 px-6 py-4 flex items-center justify-between sticky top-0 z-10">
        <div className="flex items-center gap-3">
          <div className="bg-blue-600 p-2 rounded-xl text-white shadow-lg shadow-blue-100">
            <Bot size={22} />
          </div>
          <div>
            <h1 className="font-bold text-base text-slate-800">Asisten Kominfo</h1>
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></span>
              <span className="text-[10px] text-slate-500 font-bold uppercase tracking-tight">Satu Data Banyuwangi</span>
            </div>
          </div>
        </div>
        <button
          onClick={resetChat}
          className="p-2 hover:bg-slate-100 rounded-full text-slate-400 transition-colors"
          title="Reset Percakapan"
        >
          <RefreshCw size={18} />
        </button>
      </header>

      {/* Error Alert */}
      {error && (
        <div className="bg-red-50 border-b border-red-100 px-6 py-2 flex items-center gap-2 text-red-600 text-xs font-medium">
          <AlertCircle size={14} />
          {error}
        </div>
      )}

      {/* Chat Area */}
      <main className="flex-1 overflow-y-auto px-4 py-6 md:px-0">
        <div className="max-w-3xl mx-auto space-y-6">
          {messages.map((msg, idx) => (
            <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`flex gap-3 max-w-[85%] ${msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
                <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 mt-1 shadow-sm ${
                  msg.role === 'user' ? 'bg-slate-800 text-white' : 'bg-blue-600 text-white'
                }`}>
                  {msg.role === 'user' ? <User size={14} /> : <Bot size={16} />}
                </div>
                <div className="flex flex-col gap-2">
                  <div className={`px-4 py-3 rounded-2xl text-[14px] leading-relaxed shadow-sm ${
                    msg.role === 'user'
                      ? 'bg-slate-800 text-white rounded-tr-none'
                      : 'bg-white border border-slate-200 text-slate-800 rounded-tl-none'
                  }`}>
                    {msg.content}
                  </div>
                </div>
              </div>
            </div>
          ))}

          {isTyping && (
            <div className="flex justify-start">
              <div className="flex gap-3">
                <div className="w-8 h-8 rounded-lg bg-blue-600 text-white flex items-center justify-center animate-pulse">
                  <Bot size={16} />
                </div>
                <div className="bg-white border border-slate-200 px-4 py-3 rounded-2xl rounded-tl-none shadow-sm flex items-center gap-2">
                  <Loader2 className="animate-spin text-blue-600" size={14} />
                  <span className="text-[13px] text-slate-400 italic">
                    {kbLoaded ? "Berfikir..." : "Memuat katalog dataset, dll"}
                  </span>
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </main>

      {/* Input Area */}
      <footer className="p-4 bg-white border-t border-slate-200">
        <div className="max-w-3xl mx-auto">
          <form
            onSubmit={handleSendMessage}
            className="flex items-center gap-2 bg-slate-50 border border-slate-200 rounded-2xl p-1.5 focus-within:bg-white focus-within:ring-2 focus-within:ring-blue-100 transition-all"
          >
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Tanya terkait satu data, Dataset,...."
              className="flex-1 bg-transparent px-4 py-2.5 text-sm outline-none placeholder:text-slate-400"
            />
            <button
              type="submit"
              disabled={!input.trim() || isTyping}
              className={`p-2.5 rounded-xl transition-all ${
                input.trim() && !isTyping
                  ? 'bg-blue-600 text-white shadow-md hover:bg-blue-700'
                  : 'bg-slate-200 text-slate-400'
              }`}
            >
              <Send size={18} />
            </button>
          </form>
          <p className="text-[9px] text-center text-slate-400 mt-3 font-bold uppercase tracking-[0.2em]">
            Satu Data Banyuwangi Assistant
          </p>
        </div>
      </footer>

      <style>{`
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 10px; }
        ::-webkit-scrollbar-thumb:hover { background: #94a3b8; }
      `}</style>
    </div>
  );
}
