import SwiftUI

struct GalleryView: View {
    @State private var artworks: [Artwork] = []
    @State private var searchText = ""
    @State private var selectedCollection: String?
    @State private var collections: [String] = []

    private let columns = [GridItem(.adaptive(minimum: 160), spacing: 12)]

    var filtered: [Artwork] {
        artworks.filter { art in
            art.status == .approved
            && (selectedCollection == nil || art.collection == selectedCollection)
            && (searchText.isEmpty || art.title.lowercased().contains(searchText.lowercased()))
        }
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVGrid(columns: columns, spacing: 12) {
                    ForEach(filtered) { artwork in
                        NavigationLink(value: artwork) {
                            GalleryGrid.Cell(artwork: artwork)
                        }
                    }
                }
                .padding()
            }
            .navigationTitle("Gallery")
            .searchable(text: $searchText, prompt: "Search artwork")
            .toolbar {
                if !collections.isEmpty {
                    ToolbarItem(placement: .topBarTrailing) {
                        Menu {
                            Button("All Collections") { selectedCollection = nil }
                            ForEach(collections, id: \.self) { col in
                                Button(col) { selectedCollection = col }
                            }
                        } label: {
                            Label("Collection", systemImage: "folder")
                        }
                    }
                }
            }
            .navigationDestination(for: Artwork.self) { artwork in
                ArtworkDetailView(artwork: artwork)
            }
        }
    }
}
