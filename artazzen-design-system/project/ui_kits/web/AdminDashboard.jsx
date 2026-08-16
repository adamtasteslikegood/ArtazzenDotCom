// AdminDashboard.jsx — Artazzen Design System
// Shared via window.AdminDashboard

const AdminDashboard = ({ pending = [], onReview }) => {
  const [feedback, setFeedback] = React.useState(null);
  const [aiEnabled, setAiEnabled] = React.useState(true);
  const [model, setModel] = React.useState('gpt-4o-mini');

  const handleSave = () => {
    setFeedback({ type: 'success', msg: 'AI configuration saved.' });
    setTimeout(() => setFeedback(null), 3000);
  };

  const sharedLabel = { fontFamily:"'DM Sans',sans-serif", fontSize:13, fontWeight:600, color:'#495057', display:'block', marginBottom:6 };
  const sharedInput = { width:'100%', padding:'8px 12px', border:'1px solid #ced4da', borderRadius:6, fontSize:14, fontFamily:"'DM Sans',sans-serif", outline:'none', boxSizing:'border-box' };
  const panel = { background:'#fff', border:'1px solid #dee2e6', borderRadius:8, padding:'1.25rem 1.5rem', boxShadow:'0 4px 10px rgba(0,0,0,.05)' };

  return (
    <div style={{ display:'grid', gridTemplateColumns:'1fr 1.5fr', gap:24, alignItems:'start' }}>

      {/* Upload panel */}
      <div style={panel}>
        <h2 style={{ fontFamily:"'DM Sans',sans-serif", fontSize:18, fontWeight:600, color:'#343a40', marginBottom:12 }}>Upload Artwork</h2>
        <div style={{
          border:'2px dashed #adb5bd', borderRadius:12, padding:'24px 16px',
          textAlign:'center', background:'#fdfdfe', cursor:'pointer',
          transition:'border-color .2s, background .2s',
        }}
          onMouseEnter={e => { e.currentTarget.style.borderColor='#339af0'; e.currentTarget.style.background='#e7f5ff'; }}
          onMouseLeave={e => { e.currentTarget.style.borderColor='#adb5bd'; e.currentTarget.style.background='#fdfdfe'; }}
        >
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#339af0" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{margin:'0 auto 8px'}}>
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="17 8 12 3 7 8"/>
            <line x1="12" y1="3" x2="12" y2="15"/>
          </svg>
          <p style={{ fontFamily:"'DM Sans',sans-serif", fontSize:13, color:'#495057', margin:0 }}>Drop images here or <strong>browse</strong></p>
          <p style={{ fontFamily:"'DM Sans',sans-serif", fontSize:11, color:'#6c757d', marginTop:6 }}>JPG · PNG · GIF · WEBP · SVG · BMP · TIFF</p>
        </div>

        <div style={{ marginTop:20 }}>
          <label style={sharedLabel}>AI Metadata Settings</label>
          <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:12 }}>
            <input type="checkbox" id="ai-toggle" checked={aiEnabled} onChange={e => setAiEnabled(e.target.checked)} style={{ width:16, height:16, accentColor:'#E8820A', cursor:'pointer' }} />
            <label htmlFor="ai-toggle" style={{ fontFamily:"'DM Sans',sans-serif", fontSize:13, color:'#495057', cursor:'pointer' }}>Enable AI generation</label>
          </div>
          <label style={sharedLabel}>Model</label>
          <input style={sharedInput} value={model} onChange={e => setModel(e.target.value)} disabled={!aiEnabled} />
          <button
            onClick={handleSave}
            style={{ marginTop:12, padding:'8px 18px', background:'#495057', color:'#fff', border:'none', borderRadius:6, fontFamily:"'DM Sans',sans-serif", fontSize:13, fontWeight:600, cursor:'pointer' }}
          >Save config</button>
          {feedback && (
            <div style={{ marginTop:10, padding:'8px 12px', borderRadius:6, fontSize:12, fontWeight:600,
              background: feedback.type==='success' ? '#d3f9d8' : '#ffe3e3',
              color: feedback.type==='success' ? '#2b8a3e' : '#c92a2a',
              border: `1px solid ${feedback.type==='success' ? '#b2f2bb' : '#ffa8a8'}`,
            }}>{feedback.msg}</div>
          )}
        </div>
      </div>

      {/* Pending review panel */}
      <div style={panel}>
        <h2 style={{ fontFamily:"'DM Sans',sans-serif", fontSize:18, fontWeight:600, color:'#343a40', marginBottom:4 }}>
          Pending Review
          <span style={{ marginLeft:8, background:'#343a40', color:'#fff', borderRadius:999, padding:'2px 9px', fontSize:12, fontWeight:600 }}>{pending.length}</span>
        </h2>
        <p style={{ fontFamily:"'DM Sans',sans-serif", fontSize:12, color:'#868e96', marginBottom:14 }}>Review and edit AI-generated metadata before publishing.</p>
        {pending.length === 0 ? (
          <div style={{ textAlign:'center', color:'#868e96', padding:'1.5rem', border:'1px dashed #dee2e6', borderRadius:8, fontFamily:"'DM Sans',sans-serif", fontSize:13 }}>
            All caught up — no pending items.
          </div>
        ) : (
          <div style={{ display:'flex', flexDirection:'column', gap:10, maxHeight:320, overflowY:'auto' }}>
            {pending.map(item => (
              <div key={item.name} style={{
                display:'flex', gap:12, border:'1px solid #dee2e6', borderRadius:10,
                padding:12, background:'#fff', boxShadow:'0 2px 6px rgba(0,0,0,.04)',
              }}>
                <img
                  src={item.url}
                  alt={item.title}
                  style={{ width:100, height:75, objectFit:'cover', borderRadius:6, border:'1px solid #dee2e6', flexShrink:0 }}
                  onError={e => { e.target.src='https://placehold.co/100x75/F7F4EE/adb5bd?text=?'; }}
                />
                <div style={{ flex:1, minWidth:0 }}>
                  <div style={{ fontFamily:'monospace', fontSize:10, color:'#868e96', marginBottom:3, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{item.name}</div>
                  <div style={{ fontFamily:"'DM Sans',sans-serif", fontSize:13, fontWeight:600, color:'#343a40', marginBottom:5 }}>{item.title}</div>
                  <div style={{ display:'flex', gap:4, flexWrap:'wrap' }}>
                    {item.ai_generated
                      ? <span style={{ background:'#343a40', color:'#fff', borderRadius:999, padding:'2px 8px', fontSize:10, fontWeight:600 }}>AI generated</span>
                      : <span style={{ background:'#e9ecef', color:'#495057', borderRadius:999, padding:'2px 8px', fontSize:10, fontWeight:600 }}>AI pending</span>
                    }
                    <button
                      onClick={() => onReview && onReview(item)}
                      style={{ background:'transparent', border:'1px solid #dee2e6', borderRadius:4, padding:'2px 8px', fontSize:10, fontWeight:600, color:'#495057', cursor:'pointer' }}
                    >Review →</button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

Object.assign(window, { AdminDashboard });
