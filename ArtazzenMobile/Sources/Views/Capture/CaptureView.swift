import SwiftUI
import PhotosUI

struct CaptureView: View {
    @State private var selectedItem: PhotosPickerItem?
    @State private var imageData: Data?
    @State private var isProcessing = false
    @State private var generatedArtwork: Artwork?

    var body: some View {
        NavigationStack {
            VStack(spacing: 24) {
                if let imageData, let uiImage = UIImage(data: imageData) {
                    Image(uiImage: uiImage)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .frame(maxHeight: 300)
                        .clipShape(RoundedRectangle(cornerRadius: 8))

                    if isProcessing {
                        ProgressView("Generating metadata...")
                            .font(.azBody)
                    } else if let artwork = generatedArtwork {
                        MetadataEditor(artwork: artwork)
                    }
                } else {
                    ContentUnavailableView {
                        Label("Capture Artwork", systemImage: "camera.viewfinder")
                    } description: {
                        Text("Take a photo or choose from your library to add artwork.")
                    }
                }
            }
            .padding()
            .navigationTitle("Capture")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    PhotosPicker(selection: $selectedItem, matching: .images) {
                        Label("Choose", systemImage: "photo.on.rectangle")
                    }
                }
            }
            .onChange(of: selectedItem) { _, item in
                Task {
                    guard let data = try? await item?.loadTransferable(type: Data.self) else { return }
                    imageData = data
                    isProcessing = true
                    // Upload would happen here via ArtazzenAPI
                    isProcessing = false
                }
            }
        }
    }
}
