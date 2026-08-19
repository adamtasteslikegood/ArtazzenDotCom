import SwiftUI

struct MainTabView: View {
    @State private var selectedTab = 0

    var body: some View {
        TabView(selection: $selectedTab) {
            QueueView()
                .tabItem {
                    Label("Queue", systemImage: "list.bullet")
                }
                .tag(0)

            SwipeDeckView()
                .tabItem {
                    Label("Review", systemImage: "rectangle.stack")
                }
                .tag(1)

            CaptureView()
                .tabItem {
                    Label("Capture", systemImage: "camera")
                }
                .tag(2)

            GalleryView()
                .tabItem {
                    Label("Gallery", systemImage: "photo.on.rectangle")
                }
                .tag(3)

            SettingsView()
                .tabItem {
                    Label("Settings", systemImage: "gear")
                }
                .tag(4)
        }
        .tint(Color.azTeal)
    }
}
