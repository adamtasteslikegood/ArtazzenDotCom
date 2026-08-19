import SwiftUI

struct MetadataEditor: View {
    @State var artwork: Artwork
    @State private var tagText: String = ""

    var body: some View {
        Form {
            Section("Basic Info") {
                AIFieldRow(label: "Title", field: .title, artwork: $artwork) {
                    TextField("Title", text: $artwork.title)
                }
                AIFieldRow(label: "Caption", field: .caption, artwork: $artwork) {
                    TextField("Caption", text: $artwork.caption)
                }
                AIFieldRow(label: "Description", field: .description, artwork: $artwork) {
                    TextField("Description", text: $artwork.description, axis: .vertical)
                        .lineLimit(3...6)
                }
            }

            Section("Details") {
                TextField("Artist", text: $artwork.artist)
                TextField("Copyright", text: $artwork.copyright)
                TextField("Collection", text: $artwork.collection)
            }

            Section("Tags") {
                AIFieldRow(label: "Tags", field: .tags, artwork: $artwork) {
                    HStack(spacing: 6) {
                        ForEach(artwork.tags, id: \.self) { tag in
                            TagPill(text: tag)
                        }
                    }
                }
                HStack {
                    TextField("Add tag", text: $tagText)
                        .onSubmit {
                            let tag = tagText.trimmingCharacters(in: .whitespaces).lowercased()
                            if !tag.isEmpty && !artwork.tags.contains(tag) {
                                artwork.tags.append(tag)
                            }
                            tagText = ""
                        }
                    Button("Add") {
                        let tag = tagText.trimmingCharacters(in: .whitespaces).lowercased()
                        if !tag.isEmpty && !artwork.tags.contains(tag) {
                            artwork.tags.append(tag)
                        }
                        tagText = ""
                    }
                }
            }

            Section {
                Button("Save & Approve") {
                    // API call via ArtazzenAPI.saveMetadata
                }
                .buttonStyle(.borderedProminent)
                .tint(Color.azTeal)
            }
        }
        .font(.azBody)
    }
}
