// GalleryGrid.jsx — Artazzen Design System
// Shared via window.GalleryGrid

const GalleryGrid = ({ artworks, onSelect }) => {
  if (!artworks || artworks.length === 0) {
    return (
      <div style={{
        textAlign: 'center',
        color: '#6c757d',
        padding: '3rem 2rem',
        background: '#e9ecef',
        borderRadius: 8,
        fontFamily: "'DM Sans', sans-serif",
      }}>
        <p>No artwork found. Drop images into <code style={{fontFamily:'monospace', fontSize:12}}>Static/images/</code> to get started.</p>
      </div>
    );
  }
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
      gap: 24,
    }}>
      {artworks.map(a => (
        <window.ArtworkCard key={a.name} artwork={a} onClick={onSelect} />
      ))}
    </div>
  );
};

Object.assign(window, { GalleryGrid });
