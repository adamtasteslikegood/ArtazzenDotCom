import SwiftUI

struct ArtworkDetailView: View {
    let artwork: Artwork

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                AsyncImage(url: artwork.imageURL) { image in
                    image.resizable().aspectRatio(contentMode: .fit)
                } placeholder: {
                    Rectangle().fill(Color.azCarbon.opacity(0.1))
                        .aspectRatio(4 / 5, contentMode: .fit)
                }
                .clipShape(RoundedRectangle(cornerRadius: 8))

                VStack(alignment: .leading, spacing: 16) {
                    Text(artwork.title)
                        .font(.azDisplay)

                    if !artwork.caption.isEmpty {
                        Text(artwork.caption)
                            .font(.azBody)
                            .foregroundStyle(.secondary)
                    }

                    if !artwork.description.isEmpty {
                        Text(artwork.description)
                            .font(.azBody)
                            .lineSpacing(4)
                    }

                    if !artwork.artist.isEmpty {
                        MetadataRow(label: "Artist", value: artwork.artist)
                    }

                    if !artwork.tags.isEmpty {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Tags")
                                .font(.azMono)
                                .foregroundStyle(.secondary)
                            HStack(spacing: 6) {
                                ForEach(artwork.tags, id: \.self) { tag in
                                    TagPill(text: tag)
                                }
                            }
                        }
                    }

                    if !artwork.collection.isEmpty {
                        MetadataRow(label: "Collection", value: artwork.collection)
                    }

                    if !artwork.copyright.isEmpty {
                        MetadataRow(label: "Copyright", value: artwork.copyright)
                    }
                }
                .padding(.horizontal)
            }
        }
        .navigationTitle(artwork.title)
        .navigationBarTitleDisplayMode(.inline)
    }
}

private struct MetadataRow: View {
    let label: String
    let value: String

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .font(.azMono)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.azBody)
        }
    }
}
