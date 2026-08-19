import SwiftUI

struct ReviewCard: View {
    let artwork: Artwork

    var body: some View {
        VStack(spacing: 0) {
            AsyncImage(url: artwork.imageURL) { image in
                image.resizable().aspectRatio(contentMode: .fit)
            } placeholder: {
                Rectangle().fill(Color.azCarbon.opacity(0.1))
                    .aspectRatio(4 / 5, contentMode: .fit)
            }

            VStack(alignment: .leading, spacing: 8) {
                Text(artwork.title)
                    .font(.azDisplay)
                    .lineLimit(2)

                if !artwork.caption.isEmpty {
                    Text(artwork.caption)
                        .font(.azBody)
                        .foregroundStyle(.secondary)
                }

                if !artwork.tags.isEmpty {
                    HStack(spacing: 6) {
                        ForEach(artwork.tags.prefix(5), id: \.self) { tag in
                            TagPill(text: tag)
                        }
                    }
                }
            }
            .padding()
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(Color.azParchment)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .shadow(radius: 8, x: 0, y: 4)
        .padding(.horizontal, 20)
    }
}
