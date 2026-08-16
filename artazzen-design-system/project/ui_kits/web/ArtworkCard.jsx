// ArtworkCard.jsx — Artazzen Design System
// Shared via window.ArtworkCard

const ArtworkCard = ({ artwork, onClick }) => {
  const [hovered, setHovered] = React.useState(false);
  return (
    <div
      onClick={() => onClick && onClick(artwork)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        background: '#fff',
        border: '1px solid #dee2e6',
        borderRadius: 8,
        overflow: 'hidden',
        cursor: 'pointer',
        boxShadow: hovered ? '0 6px 12px rgba(0,0,0,.10)' : '0 4px 8px rgba(0,0,0,.05)',
        transform: hovered ? 'translateY(-5px)' : 'translateY(0)',
        transition: 'transform 0.2s ease-in-out, box-shadow 0.2s ease-in-out',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <div style={{ flexShrink: 0 }}>
        <img
          src={artwork.url}
          alt={artwork.title}
          style={{
            width: '100%',
            aspectRatio: '4/3',
            objectFit: 'cover',
            display: 'block',
            background: '#f0ede6',
          }}
          onError={e => { e.target.src = 'https://placehold.co/400x300/F7F4EE/adb5bd?text=Artwork'; }}
        />
      </div>
      <div style={{ padding: '12px 14px', flex: 1 }}>
        <p style={{
          fontFamily: "'DM Sans', system-ui, sans-serif",
          fontSize: 14,
          fontWeight: 600,
          color: '#495057',
          margin: '0 0 4px',
          wordWrap: 'break-word',
        }}>{artwork.title}</p>
        {artwork.description && (
          <p style={{
            fontFamily: "'DM Sans', system-ui, sans-serif",
            fontSize: 12,
            color: '#6c757d',
            margin: 0,
            lineHeight: 1.55,
            wordWrap: 'break-word',
          }}>{artwork.description}</p>
        )}
      </div>
    </div>
  );
};

Object.assign(window, { ArtworkCard });
