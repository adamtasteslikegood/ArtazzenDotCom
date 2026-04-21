// Header.jsx — Artazzen Design System
// Shared via window.ArtazzenHeader

const ArtazzenHeader = ({ title = 'Artazzen', view, onViewChange, isAdmin }) => {
  return (
    <header style={{
      background: '#F7F4EE',
      borderBottom: '1px solid #dee2e6',
      padding: '0 2rem',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      height: 64,
      position: 'sticky',
      top: 0,
      zIndex: 100,
    }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <h1 style={{
          fontFamily: "'DM Serif Display', Georgia, serif",
          fontSize: 22,
          fontWeight: 400,
          color: '#495057',
          margin: 0,
          letterSpacing: '-0.01em',
        }}>{title}</h1>
        {isAdmin && (
          <span style={{
            fontFamily: "'DM Sans', sans-serif",
            fontSize: 10,
            fontWeight: 600,
            background: '#343a40',
            color: '#fff',
            borderRadius: 999,
            padding: '2px 8px',
            letterSpacing: '.04em',
          }}>ADMIN</span>
        )}
      </div>
      <nav style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        {[
          { id: 'gallery', label: 'Gallery' },
          { id: 'artwork', label: 'Artwork' },
          { id: 'admin', label: 'Admin' },
        ].map(item => (
          <button
            key={item.id}
            onClick={() => onViewChange(item.id)}
            style={{
              fontFamily: "'DM Sans', sans-serif",
              fontSize: 13,
              fontWeight: view === item.id ? 600 : 400,
              color: view === item.id ? '#212529' : '#6c757d',
              background: view === item.id ? '#e9ecef' : 'transparent',
              border: 'none',
              borderRadius: 6,
              padding: '6px 12px',
              cursor: 'pointer',
              transition: 'background .15s, color .15s',
            }}
          >{item.label}</button>
        ))}
      </nav>
    </header>
  );
};

Object.assign(window, { ArtazzenHeader });
