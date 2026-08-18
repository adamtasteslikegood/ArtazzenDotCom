import SwiftUI

enum GalleryGrid {
    struct Cell: View {
        let artwork: Artwork

        var body: some View {
            VStack(alignment: .leading, spacing: 6) {
                AsyncImage(url: artwork.imageURL) { image in
                    image.resizable().aspectRatio(contentMode: .fill)
                } placeholder: {
                    Rectangle().fill(Color.azCarbon.opacity(0.1))
                }
                .frame(minHeight: 160)
                .clipShape(RoundedRectangle(cornerRadius: 4))
                .overlay(alignment: .topTrailing) {
                    StatusBadge(status: artwork.status)
                        .padding(6)
                }

                Text(artwork.title)
                    .font(.azBody)
                    .fontWeight(.semibold)
                    .lineLimit(1)
                    .foregroundStyle(Color.primary)

                if !artwork.caption.isEmpty {
                    Text(artwork.caption)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
            }
        }
    }
}
