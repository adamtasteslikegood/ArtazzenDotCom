import SwiftUI

struct SwipeDeckView: View {
    @State private var pending: [Artwork] = []
    @State private var offset: CGSize = .zero

    private let threshold: CGFloat = 120

    private var topID: String? { pending.first?.id }

    var body: some View {
        NavigationStack {
            ZStack {
                if pending.isEmpty {
                    ContentUnavailableView(
                        "No Pending Artwork",
                        systemImage: "checkmark.circle",
                        description: Text("All artwork has been reviewed.")
                    )
                } else {
                    ForEach(Array(pending.enumerated().reversed()), id: \.element.id) { index, artwork in
                        let isTop = (index == 0)
                        ReviewCard(artwork: artwork)
                            .offset(isTop ? offset : .zero)
                            .rotationEffect(.degrees(isTop ? Double(offset.width) / 20 : 0))
                            .scaleEffect(isTop ? 1.0 : 0.95)
                            .gesture(
                                isTop ?
                                DragGesture()
                                    .onChanged { value in
                                        offset = value.translation
                                    }
                                    .onEnded { value in
                                        if value.translation.width > threshold {
                                            approve()
                                        } else if value.translation.width < -threshold {
                                            hide()
                                        } else {
                                            withAnimation(.spring()) { offset = .zero }
                                        }
                                    }
                                : nil
                            )
                            .animation(.spring(), value: offset)
                    }

                    VStack {
                        Spacer()
                        HStack(spacing: 48) {
                            Button { hide() } label: {
                                Image(systemName: "xmark.circle.fill")
                                    .font(.system(size: 44))
                                    .foregroundStyle(Color.azOrange)
                            }
                            Button { approve() } label: {
                                Image(systemName: "checkmark.circle.fill")
                                    .font(.system(size: 44))
                                    .foregroundStyle(Color.azTeal)
                            }
                        }
                        .padding(.bottom, 32)
                    }
                }
            }
            .navigationTitle("Review")
        }
    }

    private func approve() {
        withAnimation(.easeOut(duration: 0.3)) {
            offset = CGSize(width: 500, height: 0)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
            removeTopCard()
        }
    }

    private func hide() {
        withAnimation(.easeOut(duration: 0.3)) {
            offset = CGSize(width: -500, height: 0)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
            removeTopCard()
        }
    }

    private func removeTopCard() {
        guard !pending.isEmpty else { return }
        pending.removeFirst()
        offset = .zero
    }
}
