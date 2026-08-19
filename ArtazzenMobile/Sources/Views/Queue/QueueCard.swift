import SwiftUI

struct QueueCard: View {
    let artwork: Artwork

    var body: some View {
        HStack(spacing: 12) {
            AsyncImage(url: artwork.imageURL) { image in
                image.resizable().aspectRatio(contentMode: .fill)
            } placeholder: {
                Rectangle().fill(Color.azCarbon.opacity(0.1))
            }
            .frame(width: 64, height: 64)
            .clipShape(RoundedRectangle(cornerRadius: 4))

            VStack(alignment: .leading, spacing: 4) {
                Text(artwork.title)
                    .font(.azBody)
                    .lineLimit(1)
                Text(artwork.filename)
                    .font(.azMono)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                StatusBadge(status: artwork.status)
            }
        }
        .padding(.vertical, 4)
    }
}
