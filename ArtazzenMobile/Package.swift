// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "ArtazzenMobile",
    platforms: [.iOS(.v17)],
    products: [
        .library(name: "ArtazzenMobile", targets: ["ArtazzenMobile"]),
    ],
    targets: [
        .target(name: "ArtazzenMobile", path: "Sources"),
        .testTarget(name: "ArtazzenMobileTests", dependencies: ["ArtazzenMobile"], path: "Tests/ArtazzenMobileTests"),
    ]
)
