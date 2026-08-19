import SwiftUI

struct ArtworkCard: View {
    let artwork: Artwork
    var showStatus = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            AsyncImage(url: artwork.imageURL) { image in
                image.resizable().aspectRatio(contentMode: .fill)
            } placeholder: {
                Rectangle().fill(Color.azCarbon.opacity(0.1))
            }
            .frame(height: 200)
            .clipShape(RoundedRectangle(cornerRadius: 4))
            .overlay(alignment: .topTrailing) {
                if showStatus {
                    StatusBadge(status: artwork.status)
                        .padding(6)
                }
            }

            Text(artwork.title)
                .font(.azBody)
                .fontWeight(.semibold)
                .lineLimit(1)

            if !artwork.caption.isEmpty {
                Text(artwork.caption)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }

            if !artwork.tags.isEmpty {
                HStack(spacing: 4) {
                    ForEach(artwork.tags.prefix(3), id: \.self) { tag in
                        TagPill(text: tag)
                    }
                }
            }
        }
        .padding(12)
        .background(Color.azParchment.opacity(0.5))
        .clipShape(RoundedRectangle(cornerRadius: 6))
        .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.azCarbon.opacity(0.1), lineWidth: 1))
    }
}
